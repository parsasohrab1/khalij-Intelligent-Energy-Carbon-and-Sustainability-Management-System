"""E12 — Real-Time Optimization scheduler (FR-RTO-01).

Continuously recomputes setpoint advice from live plant state and, on a
slower cadence, queues fresh recommendations into the existing
`optimization_recommendations` table (accept -> approve -> apply). RTO never
calls `apply_recommendation` itself — every setpoint change still requires an
operator's approval, exactly like manually-triggered `/optimization/analyze`
advice.

Two run modes, mirroring `app.carbon.scheduler`:
  * inline  — started from `app.main` lifespan in dev/demo (`should_run_demo_feeder`),
              same as the demo feeder, so the zero-Docker quick start gets live RTO too.
  * standalone — `python -m app.rto.scheduler` / `make rto-scheduler`, one process
              per deployment, for full-stack / HA so recommendations aren't queued twice.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.optimization.store import persist_recommendations
from app.rto.engine import compute_rto_cycle
from app.rto.state import rto_status

logger = logging.getLogger(__name__)


class RTOScheduler:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._stop = asyncio.Event()
        self._engine = create_async_engine(
            self.settings.database_url, echo=False, pool_pre_ping=True
        )
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )
        self._last_persist: datetime | None = None

    async def stop(self) -> None:
        self._stop.set()
        await self._engine.dispose()
        rto_status.running = False

    async def run_once(self) -> int:
        plant_codes = self.settings.unit_code_list
        try:
            async with self._session_factory() as session:
                result = await compute_rto_cycle(session, plant_codes)
        except Exception:  # noqa: BLE001 — DB unreachable (memory-only demo): fall back
            result = await compute_rto_cycle(None, plant_codes)

        rto_status.last_cycle_at = result.computed_at
        now = result.computed_at
        due = (
            self._last_persist is None
            or (now - self._last_persist).total_seconds()
            >= self.settings.rto_persist_interval_seconds
        )
        if not due or not result.advice:
            return 0

        persisted = 0
        rows = []
        try:
            async with self._session_factory() as session:
                rows = await persist_recommendations(session, result.advice)
                persisted = len(rows)
        except Exception:  # noqa: BLE001
            rows = []
        if not rows and self.settings.allow_demo_memory():
            try:
                from app.demo.memory_recs import memory_recs

                rows = memory_recs.persist(result.advice)
                persisted = len(rows)
            except Exception:  # noqa: BLE001
                logger.exception("RTO memory persist failed")

        self._last_persist = now
        rto_status.last_persisted_at = now
        rto_status.last_persisted_count = persisted
        return persisted

    async def run_forever(self) -> None:
        interval = max(self.settings.rto_interval_seconds, 2)
        rto_status.running = True
        rto_status.cycle_seconds = interval
        rto_status.persist_interval_seconds = self.settings.rto_persist_interval_seconds
        logger.info(
            "RTO scheduler started interval=%ss persist=%ss plants=%s",
            interval,
            self.settings.rto_persist_interval_seconds,
            self.settings.unit_code_list,
        )
        while not self._stop.is_set():
            try:
                n = await self.run_once()
                rto_status.last_error = None
                if n:
                    logger.info(
                        "RTO cycle queued %d recommendation(s) @ %s", n, datetime.now(timezone.utc)
                    )
            except Exception as exc:  # noqa: BLE001
                rto_status.last_error = str(exc)
                logger.exception("RTO cycle failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass


async def _run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [rto-scheduler] %(message)s",
    )
    worker = RTOScheduler()
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
