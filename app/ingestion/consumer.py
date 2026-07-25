"""Kafka consumer → TimescaleDB writer (R-GEN-02)."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Any

from aiokafka import AIOKafkaConsumer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.ingestion.freshness import check_freshness, raise_alert_if_needed
from app.repositories import sensors as sensor_repo

logger = logging.getLogger(__name__)


class SensorConsumer:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._consumer: AIOKafkaConsumer | None = None
        self._stop = asyncio.Event()
        self._engine = create_async_engine(
            self.settings.database_url, echo=False, pool_pre_ping=True
        )
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            self.settings.kafka_sensor_topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=self.settings.kafka_consumer_group,
            enable_auto_commit=True,
            auto_offset_reset="latest",
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )
        await self._consumer.start()
        async with self._session_factory() as session:
            await sensor_repo.ensure_unique_index(session)
        logger.info(
            "Consumer started ← %s topic=%s group=%s",
            self.settings.kafka_bootstrap_servers,
            self.settings.kafka_sensor_topic,
            self.settings.kafka_consumer_group,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None
        await self._engine.dispose()

    async def handle_message(self, payload: dict[str, Any]) -> None:
        async with self._session_factory() as session:
            await sensor_repo.upsert_reading(session, payload)
            status = await check_freshness(
                session, payload["plant_code"], self.settings
            )
            if status.status != "ok":
                await raise_alert_if_needed(session, status, self.settings)
            logger.debug(
                "Persisted %s @ %s freshness=%s",
                payload.get("plant_code"),
                payload.get("time"),
                status.status,
            )

    async def run_forever(self) -> None:
        await self.start()
        assert self._consumer is not None
        try:
            while not self._stop.is_set():
                try:
                    batch = await self._consumer.getmany(timeout_ms=1000, max_records=100)
                except Exception:
                    if self._stop.is_set():
                        break
                    logger.exception("Kafka poll failed")
                    await asyncio.sleep(1)
                    continue

                for _tp, messages in batch.items():
                    for msg in messages:
                        try:
                            await self.handle_message(msg.value)
                        except Exception:
                            logger.exception("Failed to persist message: %s", msg.value)
        finally:
            await self.stop()


async def _run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [consumer] %(message)s",
    )
    worker = SensorConsumer()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))
        except NotImplementedError:
            pass
    await worker.run_forever()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
