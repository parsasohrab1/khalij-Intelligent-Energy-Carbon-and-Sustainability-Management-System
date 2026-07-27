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
            "endpoint": plant.endpoint,
            "tags": {
                field: {
                    "node_id": tag.node_id,
                    "unit": tag.unit,
                    "description": tag.description,
                    "scale": tag.scale,
                    "offset": tag.offset,
                }
                for field, tag in plant.tags.items()
            },
        }
        for code, plant in plants.items()
    }


@router.get("/opcua/snapshot")
async def opcua_snapshot(plant_code: str = "olefin") -> dict:
    """Live OPC/simulator snapshot including quality codes (E6)."""
    return await read_opcua_plant(plant_code)


@router.get("/plant-connect/status")
async def plant_connect_status() -> dict:
    from datetime import datetime, timezone

    from app.core.config import get_settings
    from app.demo.memory_store import memory_store
    from app.ingestion.opcua_session import get_plant_session
    from app.services.live_reading import resolve_live_reading

    cfg = get_settings()
    session = get_plant_session(cfg)
    plants_live = []
    for code in cfg.producer_plant_code_list or ["olefin"]:
        mem = memory_store.latest(code)
        age = None
        if mem is not None:
            age = max(0.0, (datetime.now(timezone.utc) - mem.time).total_seconds())
        try:
            live = await resolve_live_reading(None, code)
            plants_live.append(
                {
                    "plant_code": code,
                    "source": live.source,
                    "quality": live.quality,
                    "as_of": live.time.isoformat(),
                    "age_seconds": age,
                    "electricity_power_mw": live.electricity_power_mw,
                    "fuel_gas_flow_km3h": live.fuel_gas_flow_km3h,
                    "steam_flow_tonh": live.steam_flow_tonh,
                    "stream": "ok" if age is not None and age <= cfg.stale_data_seconds else ("stale" if age is not None else "live"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            plants_live.append({"plant_code": code, "error": str(exc)})

    return {
        "plant_connect": cfg.plant_connect,
        "ingestion_source": cfg.ingestion_source,
        "opc_ua_endpoint": cfg.opc_ua_endpoint or None,
        "opc_ua_use_subscription": cfg.opc_ua_use_subscription,
        "demo_memory_allowed": cfg.allow_demo_memory(),
        "demo_feeder": cfg.should_run_demo_feeder(),
        "opc_session_connected": session.connected,
        "plants": cfg.producer_plant_code_list,
        "live": plants_live,
    }


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
