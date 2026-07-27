"""E11 Enterprise Ops — OIDC mapping, ops status, SLO config markers."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services.auth import Role
from app.services.oidc import OidcError, decode_jwt_payload, dev_login, map_roles_from_claims, oidc_status

client = TestClient(app)


def test_map_roles_from_claims():
    assert map_roles_from_claims({"roles": ["iems-admin"]}) == Role.ADMIN
    assert map_roles_from_claims({"roles": ["iems-operator"]}) == Role.OPERATOR
    assert map_roles_from_claims({"groups": ["viewer"]}) == Role.VIEWER
    assert map_roles_from_claims({}) == Role.VIEWER


def test_decode_jwt_payload():
    # header.payload.sig — payload {"sub":"u1"}
    import base64
    import json

    payload = base64.urlsafe_b64encode(json.dumps({"sub": "u1", "roles": ["admin"]}).encode()).decode().rstrip("=")
    token = f"aaa.{payload}.bbb"
    claims = decode_jwt_payload(token)
    assert claims["sub"] == "u1"


def test_oidc_status_disabled_by_default():
    get_settings.cache_clear()
    st = oidc_status()
    assert st["enabled"] is False


def test_ops_status_endpoint():
    r = client.get("/api/v1/ops/status")
    assert r.status_code == 200
    body = r.json()
    assert "auth_enforce" in body
    assert body["slo"]["availability_target"] == 0.9995
    assert body["slo"]["availability_probe"] == "/readyz"
    assert "oidc" in body
    assert body["site_code"]


def test_oidc_dev_login_gated(monkeypatch):
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_DEV_BYPASS", "false")
    monkeypatch.setenv("APP_DEBUG", "true")
    get_settings.cache_clear()
    try:
        r = client.post(
            "/api/v1/auth/oidc/dev-login",
            json={"username": "alice", "role": "operator"},
        )
        assert r.status_code == 403
    finally:
        get_settings.cache_clear()


def test_oidc_dev_login_works(monkeypatch):
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_DEV_BYPASS", "true")
    monkeypatch.setenv("APP_DEBUG", "true")
    get_settings.cache_clear()
    try:
        result = dev_login("alice", "operator")
        assert result.ok and result.token
        r = client.post(
            "/api/v1/auth/oidc/dev-login",
            json={"username": "alice", "role": "admin"},
        )
        assert r.status_code == 200
        assert r.json()["role"] == "admin"
        assert r.json()["access_token"]
    finally:
        monkeypatch.delenv("OIDC_ENABLED", raising=False)
        monkeypatch.delenv("OIDC_DEV_BYPASS", raising=False)
        get_settings.cache_clear()


def test_oidc_login_404_when_disabled():
    get_settings.cache_clear()
    r = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 404


def test_monitoring_slo_rules_present():
    from pathlib import Path

    alerts = Path("infra/monitoring/alerts.yml").read_text(encoding="utf-8")
    assert "iems:api_availability:ratio_30d" in alerts
    assert "IEMSAvailabilitySLOBreach" in alerts
    assert Path("infra/monitoring/alertmanager.oncall.example.yml").exists()
    assert Path("infra/db/migrate_e11.sql").exists()
    assert Path("scripts/restore_timescaledb.sh").exists()


def test_dev_login_helper_raises_when_disabled():
    get_settings.cache_clear()
    try:
        dev_login("x", "operator")
        assert False, "expected OidcError"
    except OidcError:
        pass
