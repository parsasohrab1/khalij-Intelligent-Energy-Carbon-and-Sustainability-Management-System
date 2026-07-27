"""E6 Plant Connect soak — poll olefin/PTA at 1 Hz and report quality/freshness.

Usage:
  # simulator soak (no plant needed)
  python -m scripts.plant_connect_soak --seconds 30

  # real OPC (requires endpoint + tags)
  set PLANT_CONNECT=true
  set INGESTION_SOURCE=opcua
  set OPC_UA_ENDPOINT=opc.tcp://host:4840
  python -m scripts.plant_connect_soak --seconds 60 --plants olefin,pta
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from collections import defaultdict

from app.core.config import get_settings
from app.ingestion.opcua_client import read_opcua_plant
from app.ingestion.opcua_session import close_plant_session, get_plant_session


async def soak(seconds: float, plants: list[str], hz: float) -> int:
    settings = get_settings()
    interval = 1.0 / max(hz, 0.1)
    latencies: dict[str, list[float]] = defaultdict(list)
    qualities: dict[str, list[str]] = defaultdict(list)
    errors = 0
    ticks = 0
    deadline = time.monotonic() + seconds

    if settings.ingestion_source == "opcua" or settings.plant_connect:
        if settings.opc_ua_endpoint:
            await get_plant_session(settings).connect()

    print(
        f"soak start plants={plants} hz={hz} seconds={seconds} "
        f"source={settings.ingestion_source} plant_connect={settings.plant_connect} "
        f"endpoint={settings.opc_ua_endpoint or '-'}"
    )

    try:
        while time.monotonic() < deadline:
            loop_start = time.monotonic()
            for plant in plants:
                t0 = time.perf_counter()
                try:
                    sample = await read_opcua_plant(plant, settings)
                    dt_ms = (time.perf_counter() - t0) * 1000
                    latencies[plant].append(dt_ms)
                    qualities[plant].append(str(sample.get("quality") or "unknown"))
                    ticks += 1
                    print(
                        f"  {plant}: power={sample.get('electricity_power_mw')} "
                        f"quality={sample.get('quality')} source={sample.get('source')} "
                        f"{dt_ms:.1f}ms"
                    )
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    print(f"  {plant}: ERROR {exc}")
            elapsed = time.monotonic() - loop_start
            await asyncio.sleep(max(0.0, interval - elapsed))
    finally:
        await close_plant_session()

    print("\n--- soak summary ---")
    ok = errors == 0
    for plant in plants:
        lats = latencies[plant]
        qs = qualities[plant]
        if not lats:
            print(f"{plant}: no samples")
            ok = False
            continue
        good_ratio = sum(1 for q in qs if q == "good") / len(qs)
        print(
            f"{plant}: n={len(lats)} p50={statistics.median(lats):.1f}ms "
            f"max={max(lats):.1f}ms good_quality={good_ratio:.0%} errors_total={errors}"
        )
        if good_ratio < 0.9 and (settings.plant_connect or settings.ingestion_source == "opcua"):
            ok = False
    print(f"ticks={ticks} errors={errors} result={'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="E6 Plant Connect soak test")
    parser.add_argument("--seconds", type=float, default=15.0)
    parser.add_argument("--hz", type=float, default=1.0)
    parser.add_argument("--plants", type=str, default="olefin,pta")
    args = parser.parse_args()
    plants = [p.strip() for p in args.plants.split(",") if p.strip()]
    raise SystemExit(asyncio.run(soak(args.seconds, plants, args.hz)))


if __name__ == "__main__":
    main()
