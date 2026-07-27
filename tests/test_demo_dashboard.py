"""Demo memory store + feeder smoke tests."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.demo.memory_store import MemoryStore, memory_store
from app.main import app

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


def test_memory_store_roundtrip():
    store = MemoryStore(maxlen=10)
    store.append(
        {
            "time": datetime.now(timezone.utc).isoformat(),
            "plant_code": "olefin",
            "electricity_power_mw": 15.2,
            "energy_intensity_kgoe_ton": 120.5,
            "carbon_emission_kgco2_ton": 80.1,
            "energy_efficiency_percent": 88.0,
        }
    )
    latest = store.latest("olefin")
    assert latest is not None
    assert latest.electricity_power_mw == 15.2
    assert len(store.history("olefin", minutes=15)) == 1


def test_dashboard_page_has_operator_tabs():
    r = client.get("/dashboard")
    assert r.status_code == 200
    for label in ("display", "Notifications", "Graph_Analysis", "Control", "Reporting", "Connection"):
        assert label in r.text
    assert "/static/dashboard.css" in r.text
    assert 'data-view-tab="notifications"' in r.text
    assert 'id="view-notifications"' in r.text
    assert 'data-require="operate"' in r.text


def test_dashboard_reads_memory_store(monkeypatch):
    monkeypatch.setenv("DEMO_PREFER_MEMORY", "true")
    monkeypatch.setenv("DEMO_MEMORY_ONLY", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    memory_store.append(
        {
            "time": datetime.now(timezone.utc).isoformat(),
            "plant_code": "olefin",
            "electricity_power_mw": 16.0,
            "fuel_gas_flow_km3h": 105.0,
            "steam_flow_tonh": 28.0,
            "feed_flow_tonh": 102.0,
            "energy_intensity_kgoe_ton": 118.0,
            "carbon_emission_kgco2_ton": 79.0,
            "energy_efficiency_percent": 89.0,
        }
    )
    app.dependency_overrides[get_db] = _override_db
    try:
        r = client.get("/api/v1/dashboard/energy", params={"plant_code": "olefin"})
        assert r.status_code == 200
        body = r.json()
        assert body["plant_code"] == "olefin"
        assert body["electricity_power_mw"] == 16.0
        assert body["stream_status"] in {"ok", "stale"}
    finally:
        app.dependency_overrides.pop(get_db, None)
        get_settings.cache_clear()
