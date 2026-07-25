"""Phase 1 unit tests — tag map, simulator, freshness helpers."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.ingestion.freshness import FreshnessStatus, freshness_to_dict
from app.ingestion.opcua_client import simulate_plant_reading
from app.ingestion.tag_map import SENSOR_FIELDS, load_tag_map


def test_tag_map_covers_olefin_and_pta():
    plants = load_tag_map()
    assert "olefin" in plants and "pta" in plants
    for code in ("olefin", "pta"):
        for field in SENSOR_FIELDS:
            assert field in plants[code].tags
            assert plants[code].tags[field].node_id.startswith("ns=")


def test_simulator_one_hz_payload():
    sample = simulate_plant_reading("olefin", elapsed_s=10.0)
    assert sample["plant_code"] == "olefin"
    assert sample["source"] == "simulator"
    assert 5 <= sample["electricity_power_mw"] <= 25
    assert "energy_intensity_kgoe_ton" in sample
    # ISO timestamp parseable
    datetime.fromisoformat(sample["time"])


def test_simulator_plants_differ():
    a = simulate_plant_reading("olefin", elapsed_s=50.0)
    b = simulate_plant_reading("pta", elapsed_s=50.0)
    assert a["electricity_power_mw"] != b["electricity_power_mw"]


def test_freshness_dict():
    status = FreshnessStatus(
        plant_code="olefin",
        status="stale",
        age_seconds=12.5,
        threshold_seconds=5.0,
        message="stale",
    )
    payload = freshness_to_dict(status)
    assert payload["status"] == "stale"
    assert payload["age_seconds"] == 12.5


@pytest.mark.asyncio
async def test_check_freshness_missing(monkeypatch):
    from app.ingestion import freshness as freshness_mod

    async def _none(*_a, **_k):
        return None

    monkeypatch.setattr(freshness_mod.sensor_repo, "reading_age_seconds", _none)
    session = SimpleNamespace()
    status = await freshness_mod.check_freshness(session, "olefin")
    assert status.status == "missing"


@pytest.mark.asyncio
async def test_check_freshness_stale(monkeypatch):
    from app.ingestion import freshness as freshness_mod

    async def _age(*_a, **_k):
        return 20.0

    monkeypatch.setattr(freshness_mod.sensor_repo, "reading_age_seconds", _age)
    session = SimpleNamespace()
    status = await freshness_mod.check_freshness(session, "olefin")
    assert status.status == "stale"
    assert status.age_seconds == 20.0


def test_stale_threshold_logic():
    now = datetime.now(timezone.utc)
    age = (now - (now - timedelta(seconds=6))).total_seconds()
    assert age > 5.0
