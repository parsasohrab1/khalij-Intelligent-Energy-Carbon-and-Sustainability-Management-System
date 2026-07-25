"""Kafka producer worker — poll OPC-UA/simulator at ≥1 Hz (R-GEN-01)."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Any

from aiokafka import AIOKafkaProducer

from app.core.config import Settings, get_settings
from app.ingestion.opcua_client import read_opcua_plant

logger = logging.getLogger(__name__)


class SensorProducer:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._producer: AIOKafkaProducer | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda v: v.encode("utf-8") if v else None,
        )
        await self._producer.start()
        logger.info(
            "Producer started → %s topic=%s rate=%.2f Hz plants=%s source=%s",
            self.settings.kafka_bootstrap_servers,
            self.settings.kafka_sensor_topic,
            self.settings.ingestion_rate_hz,
            self.settings.producer_plant_code_list,
            self.settings.ingestion_source,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, payload: dict[str, Any]) -> None:
        assert self._producer is not None
        await self._producer.send_and_wait(
            self.settings.kafka_sensor_topic,
            value=payload,
            key=payload.get("plant_code", "unknown"),
        )

    async def tick(self) -> list[dict[str, Any]]:
        published: list[dict[str, Any]] = []
        for plant_code in self.settings.producer_plant_code_list:
            payload = await read_opcua_plant(plant_code, self.settings)
            await self.publish(payload)
            published.append(payload)
            logger.debug(
                "Published %s @ %s power=%.2f MW",
                plant_code,
                payload["time"],
                payload["electricity_power_mw"],
            )
        return published

    async def run_forever(self) -> None:
        interval = 1.0 / max(self.settings.ingestion_rate_hz, 0.1)
        await self.start()
        try:
            while not self._stop.is_set():
                loop_start = asyncio.get_event_loop().time()
                try:
                    await self.tick()
                except Exception:
                    logger.exception("Producer tick failed")
                elapsed = asyncio.get_event_loop().time() - loop_start
                remaining = max(0.0, interval - elapsed)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.stop()


async def _run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [producer] %(message)s",
    )
    worker = SensorProducer()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))
        except NotImplementedError:
            # Windows
            pass

    await worker.run_forever()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
