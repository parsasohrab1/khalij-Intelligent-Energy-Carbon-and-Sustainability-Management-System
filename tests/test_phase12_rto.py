"""E12 — Real-Time Optimization (RTO): live cycle, API surface, scheduler queueing."""

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.demo.memory_recs import memory_recs
from app.main import app
from app.rto.engine import RTO_TAG, compute_rto_cycle
from app.rto.scheduler import RTOScheduler
from app.rto.state import rto_status

client = TestClient(app)


class _FakeResult:
    def first(self):
        return None

    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return self

    def all(self):
        return []


class _FakeSession:
    async def execute(self, *_a, **_k):
        return _FakeResult()

    async def commit(self):
        return None


async def _override_db():
    yield _FakeSession()


async def test_compute_rto_cycle_tags_advice_and_benchmarks():
    result = await compute_rto_cycle(None, ["olefin", "pta"])
    assert len(result.units) == 2
    assert {b.tier for b in result.units} <= {"high", "low"}
    for advice in result.advice:
        assert RTO_TAG in advice.tags
        assert advice.deltas


def test_rto_live_endpoint_returns_units(monkeypatch):
    monkeypatch.setenv("DEMO_PREFER_MEMORY", "true")
    monkeypatch.setenv("DEMO_MEMORY_ONLY", "true")
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = _override_db
    try:
        r = client.get("/api/v1/rto/live", params={"plant_codes": "olefin,pta"})
        assert r.status_code == 200
        body = r.json()
        assert body["units"]
        codes = {u["plant_code"] for u in body["units"]}
        assert codes == {"olefin", "pta"}
        assert "computed_at" in body
    finally:
        app.dependency_overrides.pop(get_db, None)
        get_settings.cache_clear()


def test_rto_status_endpoint_reports_not_running_by_default():
    rto_status.running = False
    r = client.get("/api/v1/rto/status")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is False
    assert "cycle_seconds" in body


async def test_scheduler_queues_recommendation_into_memory_store():
    # Deliberately unreachable DB host: exercises the memory-fallback path
    # (persist_recommendations fails -> memory_recs.persist) without touching
    # a real database, regardless of what's running on the dev machine.
    settings = Settings(postgres_host="rto-test-invalid-host", unit_codes="olefin,pta")
    before = len(memory_recs.list(limit=1000))

    scheduler = RTOScheduler(settings)
    try:
        persisted = await scheduler.run_once()
        after = len(memory_recs.list(limit=1000))
        assert after - before == persisted
    finally:
        await scheduler.stop()
