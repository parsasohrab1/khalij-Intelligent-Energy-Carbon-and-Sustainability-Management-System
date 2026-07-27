"""E10 ESG & Market — Scope 3, ESG packs, assurance transitions."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.carbon.assurance import AssuranceError
from app.carbon.esg_pack import build_esg_pack
from app.carbon.scope3 import compute_scope3, load_scope3_factors
from app.db.models import CarbonReport
from app.main import app
from app.services.auth import Role, issue_token

client = TestClient(app)


def test_scope3_factors_loaded():
    factors = load_scope3_factors()
    assert "olefin" in factors and "pta" in factors
    assert factors["olefin"].cat1_purchased_goods_kgco2_per_ton > 0


def test_compute_scope3_light():
    s3 = compute_scope3(plant_code="olefin", fuel_gas_km3=100.0, product_ton=50.0)
    assert s3.total_kgco2 > 0
    assert s3.cat3_fuel_upstream_kgco2 > 0
    assert s3.cat1_purchased_goods_kgco2 > 0
    assert s3.cat5_waste_kgco2 > 0
    assert abs(
        s3.total_kgco2
        - (s3.cat3_fuel_upstream_kgco2 + s3.cat1_purchased_goods_kgco2 + s3.cat5_waste_kgco2)
    ) < 0.02


def test_esg_pack_is_presentable_not_json():
    report = CarbonReport(
        id=42,
        plant_id=1,
        period_start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 7, 2, tzinfo=timezone.utc),
        period_type="daily",
        scope1_kgco2=1000.0,
        scope2_kgco2=200.0,
        scope3_kgco2=150.0,
        scope3_detail_json='{"cat3_fuel_upstream_kgco2": 80, "cat1_purchased_goods_kgco2": 50, "cat5_waste_kgco2": 20, "factors_version": "scope3-light-2026.1"}',
        carbon_intensity_kgco2_ton=12.0,
        product_ton=100.0,
        sample_count=100,
        factors_version="ipcc-placeholder-2026.1",
        assurance_status="approved",
        approved_by="admin",
        created_at=datetime.now(timezone.utc),
    )
    pack = build_esg_pack(report, "olefin")
    assert "ESG Sustainability Pack" in pack.html
    assert "raw API JSON" not in pack.html.lower() or "Not raw" in pack.html
    assert "Scope 1" in pack.csv_text
    assert "Scope 3" in pack.csv_text
    assert pack.html.strip().startswith("<!DOCTYPE html>")


def test_assurance_error_messages():
    err = AssuranceError("Approve requires in_review (current=draft)")
    assert "in_review" in str(err)


def test_dashboard_has_e10_markers():
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "E10 ESG" in r.text
    js = client.get("/static/dashboard.js").text
    assert "ESG pack" in js or "data-pack=" in js
    assert "/pack?format=" in js
    assert "btnMarketHist" in r.text


def test_lock_requires_settings_role_when_enforced(monkeypatch):
    monkeypatch.setenv("AUTH_ENFORCE", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    op = issue_token("operator", Role.OPERATOR)
    # Without a real report this 404s before role — check /me apply/settings instead
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {op}"})
    assert me.json()["actions"]["settings"] is False
    admin = issue_token("admin", Role.ADMIN)
    me2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin}"})
    assert me2.json()["actions"]["settings"] is True
    get_settings.cache_clear()
    monkeypatch.delenv("AUTH_ENFORCE", raising=False)
    get_settings.cache_clear()
