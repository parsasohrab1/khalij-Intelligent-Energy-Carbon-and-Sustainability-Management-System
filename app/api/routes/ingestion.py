"""FR-DATA-01 / FR-DATA-02 — ingestion endpoints + tag map."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.ingestion.opcua_client import read_opcua_plant
from app.ingestion.tag_map import get_tag_map
from app.repositories import sensors as sensor_repo
from app.schemas import SensorReadingIn, SensorReadingOut
from app.services.ingestion import publish_sensor_event
from app.services.physics import enrich_reading

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.get("/tags")
async def list_tag_map() -> dict:
    plants = get_tag_map()
    return {
        code: {
            "name": plant.name,
            "tags": {
                field: {
                    "node_id": tag.node_id,
                    "unit": tag.unit,
                    "description": tag.description,
                }
                for field, tag in plant.tags.items()
            },
        }
        for code, plant in plants.items()
    }


@router.get("/opcua/snapshot", response_model=SensorReadingOut)
async def opcua_snapshot(plant_code: str = "olefin") -> SensorReadingOut:
    snap = await read_opcua_plant(plant_code)
    return SensorReadingOut(
        time=datetime.fromisoformat(snap["time"].replace("Z", "+00:00")),
        plant_code=plant_code,
        electricity_power_mw=snap.get("electricity_power_mw"),
        fuel_gas_flow_km3h=snap.get("fuel_gas_flow_km3h"),
        steam_flow_tonh=snap.get("steam_flow_tonh"),
        feed_flow_tonh=snap.get("feed_flow_tonh"),
        reactor_temp_c=snap.get("reactor_temp_c"),
        pressure_bar=snap.get("pressure_bar"),
        energy_intensity_kgoe_ton=snap.get("energy_intensity_kgoe_ton"),
        carbon_emission_kgco2_ton=snap.get("carbon_emission_kgco2_ton"),
        energy_efficiency_percent=snap.get("energy_efficiency_percent"),
    )


@router.post("/readings", response_model=SensorReadingOut)
async def ingest_reading(
    payload: SensorReadingIn,
    db: AsyncSession = Depends(get_db),
) -> SensorReadingOut:
    ts = payload.time or datetime.now(timezone.utc)
    base = {
        "electricity_power_mw": payload.electricity_power_mw or 15.0,
        "fuel_gas_flow_km3h": payload.fuel_gas_flow_km3h or 100.0,
        "steam_flow_tonh": payload.steam_flow_tonh or 30.0,
        "feed_flow_tonh": payload.feed_flow_tonh or 100.0,
        "reactor_temp_c": payload.reactor_temp_c or 400.0,
    }
    derived = enrich_reading(**base)
    event = {
        "time": ts.isoformat(),
        "plant_code": payload.plant_code,
        **base,
        "pressure_bar": payload.pressure_bar,
        **derived,
        "source": "api",
    }
    await publish_sensor_event(event)
    # Also persist directly so dashboard works even if Kafka is briefly down
    await sensor_repo.upsert_reading(db, event)
    return SensorReadingOut(
        time=ts,
        plant_code=payload.plant_code,
        pressure_bar=payload.pressure_bar,
        **base,
        **derived,
    )
