"""Process-local RTO scheduler status, best-effort, for GET /rto/status.

Populated only when `RTOScheduler.run_forever` is running in *this* process
(inline demo mode). In a multi-replica deployment with a standalone
`app.rto.scheduler` worker, `/rto/status` on an API replica correctly
reports `running=False` while `/rto/live` still returns fresh advice
(computed on read, independent of the scheduler).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RTOStatus:
    running: bool = False
    cycle_seconds: float = 10.0
    persist_interval_seconds: float = 120.0
    last_cycle_at: datetime | None = None
    last_persisted_at: datetime | None = None
    last_persisted_count: int = 0
    last_error: str | None = None


rto_status = RTOStatus()
