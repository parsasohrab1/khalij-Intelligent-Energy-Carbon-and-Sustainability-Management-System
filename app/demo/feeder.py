"""Kafka-less 1 Hz feeder — writes simulator samples to memory and/or TimescaleDB."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.demo.memory_store import memory_store
from app.ingestion.opcua_client import read_opcua_plant
from app.repositories import sensors as sensor_repo

logger = logging.getLogger(__name__)


class DemoFeeder:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._stop = asyncio.Event()
        self._engine = None
        self._session_factory = None
        if not self.settings.demo_memory_only:
            self._engine = create_async_engine(
                self.settings.database_url, echo=False, pool_pre_ping=True
            )
            self._session_factory = async_sessionmaker(
                self._engine, class_=AsyncSession, expire_on_commit=False
            )

    async def stop(self) -> None:
        self._stop.set()
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    async def _persist_db(self, payload: dict[str, Any]) -> None:
        if self._session_factory is None:
            return
        try:
            async with self._session_factory() as session:
                await sensor_repo.upsert_reading(session, payload)
        except Exception:
            logger.warning(
                "Demo feeder DB persist disabled after failure for %s",
                payload.get("plant_code"),
            )
            self._session_factory = None
            if self._engine is not None:
                try:
                    await self._engine.dispose()
                except Exception:  # noqa: BLE001
                    pass
                self._engine = None

    async def tick(self) -> list[dict[str, Any]]:
        published: list[dict[str, Any]] = []
        plants = self.settings.producer_plant_code_list or ["olefin", "pta"]
        for plant_code in plants:
            payload = await read_opcua_plant(plant_code, self.settings)
            payload["source"] = "demo-feeder"
            memory_store.append(payload)
            await self._persist_db(payload)
            published.append(payload)
        return published

    async def run_forever(self) -> None:
        interval = 1.0 / max(self.settings.ingestion_rate_hz, 0.1)
        logger.info(
            "Demo feeder started rate=%.2f Hz plants=%s memory_only=%s",
            self.settings.ingestion_rate_hz,
            self.settings.producer_plant_code_list,
            self.settings.demo_memory_only,
        )
        try:
            while not self._stop.is_set():
                loop_start = asyncio.get_event_loop().time()
                try:
                    await self.tick()
                except Exception:
                    logger.exception("Demo feeder tick failed")
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
        format="%(asctime)s %(levelname)s [demo-feeder] %(message)s",
    )
    worker = DemoFeeder()
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
