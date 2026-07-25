"""FR-DATA-01 / FR-DATA-02 — Kafka publish helper + OPC snapshot compatibility."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import Settings, get_settings
from app.ingestion.opcua_client import read_opcua_plant

logger = logging.getLogger(__name__)


async def read_opcua_snapshot(plant_code: str = "olefin") -> dict[str, Any]:
    """Backward-compatible wrapper used by optimization/carbon routes."""
    return await read_opcua_plant(plant_code)


async def publish_sensor_event(payload: dict[str, Any], settings: Settings | None = None) -> bool:
    """Publish a sensor reading to Kafka (R-GEN-01 stream path)."""
    cfg = settings or get_settings()
    try:
        from aiokafka import AIOKafkaProducer
    except ImportError:
        logger.warning("aiokafka unavailable; skipping publish")
        return False

    producer = AIOKafkaProducer(bootstrap_servers=cfg.kafka_bootstrap_servers)
    try:
        await producer.start()
        await producer.send_and_wait(
            cfg.kafka_sensor_topic,
            json.dumps(payload, default=str).encode("utf-8"),
        )
        return True
    except Exception:
        logger.exception("Kafka publish failed")
        return False
    finally:
        await producer.stop()
