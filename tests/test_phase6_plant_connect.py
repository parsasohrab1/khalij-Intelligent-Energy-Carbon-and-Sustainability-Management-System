"""E6 Plant Connect — quality codes, tag scale, plant_connect gating."""

from pathlib import Path

import pytest

from app.core.config import Settings
from app.ingestion.opcua_client import read_opcua_plant, simulate_plant_reading
from app.ingestion.quality import (
    QualityCode,
    aggregate_quality,
    apply_scale,
    quality_is_healthy,
    status_code_to_quality,
)
from app.ingestion.tag_map import SENSOR_FIELDS, load_tag_map


def test_status_code_quality_mapping():
    assert status_code_to_quality(0x00000000) == QualityCode.GOOD
    assert status_code_to_quality(0x40000000) == QualityCode.UNCERTAIN
    assert status_code_to_quality(0x80000000) == QualityCode.BAD
    assert status_code_to_quality(None) == QualityCode.UNKNOWN


def test_aggregate_quality_worst_wins():
    assert aggregate_quality({"a": QualityCode.GOOD, "b": QualityCode.BAD}) == QualityCode.BAD
    assert aggregate_quality({"a": QualityCode.GOOD, "b": QualityCode.UNCERTAIN}) == QualityCode.UNCERTAIN


def test_quality_health_gate():
    assert quality_is_healthy(QualityCode.GOOD)
    assert quality_is_healthy(QualityCode.UNCERTAIN, allow_uncertain=True)
    assert not quality_is_healthy(QualityCode.UNCERTAIN, allow_uncertain=False)
    assert not quality_is_healthy(QualityCode.BAD)


def test_apply_scale_offset():
    assert apply_scale(10.0, scale=0.1, offset=1.0) == pytest.approx(2.0)


def test_tag_map_has_scale_fields():
    plants = load_tag_map()
    for code in ("olefin", "pta"):
        for field in SENSOR_FIELDS:
            tag = plants[code].tags[field]
            assert tag.scale == 1.0
            assert tag.offset == 0.0
            assert tag.node_id.startswith("ns=")


def test_simulator_includes_quality():
    sample = simulate_plant_reading("olefin", elapsed_s=1.0)
    assert sample["quality"] == "good"
    assert sample["quality_ok"] is True
    assert set(sample["quality_detail"]) == set(SENSOR_FIELDS)


@pytest.mark.asyncio
async def test_plant_connect_requires_endpoint(monkeypatch):
    cfg = Settings(
        plant_connect=True,
        ingestion_source="opcua",
        opc_ua_endpoint="",
    )
    with pytest.raises(RuntimeError, match="OPC_UA_ENDPOINT"):
        await read_opcua_plant("olefin", cfg)


def test_settings_block_demo_memory_in_plant_connect():
    cfg = Settings(
        plant_connect=True,
        demo_feeder=True,
        demo_prefer_memory=True,
        demo_memory_only=True,
    )
    assert cfg.allow_demo_memory() is False
    assert cfg.plant_connect_active is True


def test_settings_allow_demo_memory_normally():
    cfg = Settings(plant_connect=False, demo_prefer_memory=True)
    assert cfg.allow_demo_memory() is True


def test_tags_yaml_exists():
    root = Path(__file__).resolve().parents[1]
    assert (root / "infra" / "opcua" / "tags.yaml").is_file()
    assert (root / "infra" / "db" / "migrate_e6.sql").is_file()
