"""Phase 1 ingestion package — OPC-UA, Kafka, freshness."""

from app.ingestion.opcua_client import read_opcua_plant, simulate_plant_reading
from app.ingestion.tag_map import get_tag_map, load_tag_map

__all__ = [
    "get_tag_map",
    "load_tag_map",
    "read_opcua_plant",
    "simulate_plant_reading",
]
