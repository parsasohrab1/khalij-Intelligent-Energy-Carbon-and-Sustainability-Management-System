"""Scheduled automatic sustainability report generation (R-GEN-04)."""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.carbon.reports import PeriodType, generate_and_persist_report
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class CarbonReportScheduler:
    """
    Periodically generates daily/monthly/yearly Scope 1/2 reports.

    In development, `completed_only=False` can be used via settings so the
    current in-progress day still produces a report for demos.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._stop = asyncio.Event()
        self._engine = create_async_engine(
            self.settings.database_url, echo=False, pool_pre_ping=True
        )
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def stop(self) -> None:
        self._stop.set()
        await self._engine.dispose()

    async def run_once(self) -> dict[str, int]:
        export_dir = Path(self.settings.carbon_reports_export_dir)
        if not export_dir.is_absolute():
            export_dir = Path(__file__).resolve().parents[2] / export_dir

        counts = {"daily": 0, "monthly": 0, "yearly": 0, "errors": 0}
        periods: list[PeriodType] = ["daily", "monthly", "yearly"]
        completed_only = self.settings.carbon_report_completed_only

        async with self._session_factory() as session:
            for plant_code in self.settings.unit_code_list:
                for period in periods:
                    try:
                        result = await generate_and_persist_report(
                            session,
                            plant_code,
                            period,
                            completed_only=completed_only,
                            export_dir=export_dir,
                        )
                        if result is not None:
                            counts[period] += 1
                            logger.info(
                                "Report %s/%s id=%s intensity=%.2f",
                                plant_code,
                                period,
                                result.report.id,
                                result.report.carbon_intensity_kgco2_ton or 0,
                            )
                    except Exception:
                        counts["errors"] += 1
                        logger.exception("Failed report %s/%s", plant_code, period)
        return counts

    async def run_forever(self) -> None:
        interval = max(self.settings.carbon_report_interval_seconds, 30)
        logger.info(
            "Carbon report scheduler started interval=%ss plants=%s completed_only=%s",
            interval,
            self.settings.unit_code_list,
            self.settings.carbon_report_completed_only,
        )
        while not self._stop.is_set():
            try:
                counts = await self.run_once()
                logger.info("Scheduler cycle done: %s @ %s", counts, datetime.now(timezone.utc))
            except Exception:
                logger.exception("Scheduler cycle failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass


async def _run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [carbon-scheduler] %(message)s",
    )
    worker = CarbonReportScheduler()
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
