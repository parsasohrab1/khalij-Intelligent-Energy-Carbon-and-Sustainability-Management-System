"""Periodic model retraining worker (Phase 3)."""

from __future__ import annotations

import asyncio
import logging
import signal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.ml.train import train_model

logger = logging.getLogger(__name__)


class ModelTrainer:
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

    async def run_once(self) -> dict[str, object]:
        from app.ml.train import TrustedDataError, evaluate_drift

        results: dict[str, object] = {}
        async with self._session_factory() as session:
            for plant in self.settings.unit_code_list:
                for kind in ("elm", "lstm"):
                    key = f"{plant}:{kind}"
                    try:
                        if self.settings.trusted_mode_active:
                            drift = await evaluate_drift(
                                session,
                                plant_code=plant,
                                kind=kind,  # type: ignore[arg-type]
                                settings=self.settings,
                            )
                            if drift.get("status") == "ok" and not drift.get("drift_alert"):
                                results[key] = {
                                    "skipped": True,
                                    "reason": "no_drift",
                                    "max_psi": drift.get("max_psi"),
                                }
                                logger.info(
                                    "Skip retrain %s/%s — no drift (max_psi=%s)",
                                    plant,
                                    kind,
                                    drift.get("max_psi"),
                                )
                                continue
                        outcome = await train_model(
                            kind=kind,  # type: ignore[arg-type]
                            plant_code=plant,
                            session=session,
                            settings=self.settings,
                        )
                        results[key] = {
                            "mape": outcome.mape,
                            "meets_target": outcome.meets_mape_target,
                            "version": outcome.registered.version,
                            "source": outcome.data_source,
                            "trusted": outcome.trusted,
                            "holdout_temporal": outcome.holdout_temporal,
                        }
                        logger.info(
                            "Trained %s/%s mape=%.3f target_ok=%s version=%s trusted=%s",
                            plant,
                            kind,
                            outcome.mape,
                            outcome.meets_mape_target,
                            outcome.registered.version,
                            outcome.trusted,
                        )
                    except TrustedDataError as exc:
                        logger.error("Trusted train blocked for %s/%s: %s", plant, kind, exc)
                        results[key] = {"error": True, "trusted_blocked": True, "detail": str(exc)}
                    except Exception:
                        logger.exception("Training failed for %s/%s", plant, kind)
                        results[key] = {"error": True}
        return results

    async def run_forever(self) -> None:
        interval = max(self.settings.ml_retrain_interval_seconds, 60)
        logger.info("ML trainer started interval=%ss", interval)
        # Train immediately on boot so API has models
        await self.run_once()
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                await self.run_once()


async def _run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [ml-trainer] %(message)s",
    )
    worker = ModelTrainer()
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
