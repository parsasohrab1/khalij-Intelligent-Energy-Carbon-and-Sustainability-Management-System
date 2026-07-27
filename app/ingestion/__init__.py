"""Phase 1 / E6 ingestion package — OPC-UA, Kafka, freshness, quality."""

from app.ingestion.opcua_client import read_opcua_plant, simulate_plant_reading
from app.ingestion.quality import QualityCode, status_code_to_quality
from app.ingestion.tag_map import get_tag_map, load_tag_map, reload_tag_map

__all__ = [
    "QualityCode",
    "get_tag_map",
    "load_tag_map",
    "read_opcua_plant",
    "reload_tag_map",
    "simulate_plant_reading",
    "status_code_to_quality",
]
