"""API smoke tests with FastAPI TestClient."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app

client = TestClient(app)


class _FakeResult:
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def first(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value or []


class _FakeSession:
    async def execute(self, *_a, **_k):
        return _FakeResult(None)

    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None

    def add(self, _obj):
        return None


async def _override_db():
    yield _FakeSession()


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["app"] == "iEMS"


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in {"ok", "degraded"}


def test_tag_map_endpoint():
    r = client.get("/api/v1/ingestion/tags")
    assert r.status_code == 200
    body = r.json()
    assert "olefin" in body
    assert "electricity_power_mw" in body["olefin"]["tags"]


def test_dashboard_energy_404_without_data():
    app.dependency_overrides[get_db] = _override_db
    try:
        r = client.get("/api/v1/dashboard/energy", params={"plant_code": "olefin"})
        assert r.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_dashboard_energy_with_reading():
    plant = SimpleNamespace(id=1, code="olefin")
    reading = SimpleNamespace(
        time=datetime.now(timezone.utc),
        electricity_power_mw=15.0,
        fuel_gas_flow_km3h=100.0,
        steam_flow_tonh=30.0,
        feed_flow_tonh=100.0,
        energy_intensity_kgoe_ton=650.0,
        carbon_emission_kgco2_ton=45.0,
        energy_efficiency_percent=78.0,
    )

    async def _override():
        session = _FakeSession()
        yield session

    app.dependency_overrides[get_db] = _override

    from app.api.routes import dashboard as dash_mod

    original = dash_mod.sensor_repo.get_latest_reading
    original_fresh = dash_mod.check_freshness
    original_alert = dash_mod.raise_alert_if_needed

    dash_mod.sensor_repo.get_latest_reading = AsyncMock(return_value=(plant, reading))
    dash_mod.check_freshness = AsyncMock(
        return_value=SimpleNamespace(status="ok", age_seconds=0.5, message="ok")
    )
    dash_mod.raise_alert_if_needed = AsyncMock(return_value=None)
    try:
        r = client.get("/api/v1/dashboard/energy", params={"plant_code": "olefin"})
        assert r.status_code == 200
        body = r.json()
        assert body["plant_code"] == "olefin"
        assert body["stream_status"] == "ok"
        assert body["carbon_intensity_kgco2_ton"] is not None
    finally:
        dash_mod.sensor_repo.get_latest_reading = original
        dash_mod.check_freshness = original_fresh
        dash_mod.raise_alert_if_needed = original_alert
        app.dependency_overrides.clear()


def test_predict():
    async def _override():
        yield _FakeSession()

    app.dependency_overrides[get_db] = _override
    from app.api.routes import prediction as pred_mod

    original_resolve = pred_mod.resolve_features
    original_persist = pred_mod.persist_prediction
    pred_mod.resolve_features = AsyncMock(
        return_value={
            "electricity_power_mw": 15.0,
            "fuel_gas_flow_km3h": 100.0,
            "steam_flow_tonh": 30.0,
            "feed_flow_tonh": 100.0,
            "reactor_temp_c": 400.0,
        }
    )
    pred_mod.persist_prediction = AsyncMock(return_value=None)
    try:
        r = client.post(
            "/api/v1/ml/predict",
            json={"plant_code": "olefin", "horizon_minutes": 60, "model": "elm"},
        )
        assert r.status_code == 200
        assert r.json()["latency_ms"] < 3000
        assert r.json()["predicted_energy_kwh"] > 0
    finally:
        pred_mod.resolve_features = original_resolve
        pred_mod.persist_prediction = original_persist
        app.dependency_overrides.clear()


def test_carbon_factors():
    r = client.get("/api/v1/carbon/factors")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 2
    codes = {item["plant_code"] for item in body}
    assert "olefin" in codes and "pta" in codes


def test_carbon_scopes_instant():
    plant = SimpleNamespace(id=1, code="olefin")
    reading = SimpleNamespace(
        time=datetime.now(timezone.utc),
        electricity_power_mw=15.0,
        fuel_gas_flow_km3h=100.0,
        steam_flow_tonh=30.0,
        feed_flow_tonh=100.0,
    )

    async def _override():
        yield _FakeSession()

    app.dependency_overrides[get_db] = _override
    from app.api.routes import carbon as carbon_mod

    original = carbon_mod.sensor_repo.get_latest_reading
    carbon_mod.sensor_repo.get_latest_reading = AsyncMock(return_value=(plant, reading))
    try:
        r = client.get(
            "/api/v1/carbon/scopes",
            params={"plant_code": "olefin", "period_type": "instant"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["scope1_kgco2"] > 0
        assert body["scope2_kgco2"] > 0
        assert body["factors_version"]
    finally:
        carbon_mod.sensor_repo.get_latest_reading = original
        app.dependency_overrides.clear()


def test_carbon_kpi_endpoint():
    async def _override():
        yield _FakeSession()

    app.dependency_overrides[get_db] = _override
    from app.api.routes import carbon as carbon_mod

    carbon_mod.sensor_repo.get_latest_reading = AsyncMock(return_value=None)
    carbon_mod.list_reports = AsyncMock(return_value=[])
    try:
        r = client.get("/api/v1/carbon/kpi/intensity", params={"plant_code": "olefin"})
        assert r.status_code == 200
        assert r.json()["kpi"] == "carbon_intensity"
    finally:
        app.dependency_overrides.clear()


def test_optimization_analyze():
    async def _override():
        yield _FakeSession()

    app.dependency_overrides[get_db] = _override
    try:
        r = client.post(
            "/api/v1/optimization/analyze",
            json={
                "plant_codes": ["olefin", "pta"],
                "simulate": True,
                "persist": False,
                "model": "elm",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["units"]) == 2
        assert "recommendations" in body
        assert body["total_estimated_saving_kwh_per_h"] >= 0
    finally:
        app.dependency_overrides.clear()
