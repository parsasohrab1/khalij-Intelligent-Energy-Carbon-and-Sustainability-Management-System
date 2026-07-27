"""Phase 5 — security (RBAC/TOTP), metrics, readiness."""

from fastapi.testclient import TestClient

from app.main import app
from app.security.totp import totp, verify_totp
from app.services.auth import (
    DEMO_TOTP_SECRET,
    Role,
    authenticate,
    hash_password,
    issue_token,
    role_allows,
    verify_password,
    verify_settings_2fa,
    verify_token,
)

client = TestClient(app)


def test_password_hash_roundtrip():
    encoded = hash_password("secret", salt="ab" * 16)
    assert verify_password("secret", encoded)
    assert not verify_password("nope", encoded)


def test_totp_window():
    code = totp(DEMO_TOTP_SECRET)
    assert verify_totp(DEMO_TOTP_SECRET, code)
    assert not verify_totp(DEMO_TOTP_SECRET, "000000")


def test_token_issue_and_verify():
    token = issue_token("admin", Role.ADMIN, ttl_seconds=60)
    result = verify_token(token)
    assert result.ok and result.username == "admin"


def test_login_and_settings_with_2fa():
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    denied = client.patch(
        "/api/v1/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"stale_data_seconds": 8},
    )
    assert denied.status_code == 401
    assert denied.headers.get("x-requires-2fa") == "true"

    code = totp(DEMO_TOTP_SECRET)
    assert verify_settings_2fa("admin", code)
    ok = client.patch(
        "/api/v1/settings",
        headers={"Authorization": f"Bearer {token}", "X-2FA-Code": code},
        json={"stale_data_seconds": 8},
    )
    assert ok.status_code == 200
    assert ok.json()["stale_data_seconds"] == 8


def test_viewer_cannot_settings():
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer", "password": "viewer"},
    )
    token = login.json()["access_token"]
    assert role_allows(Role.VIEWER, "read")
    r = client.get(
        "/api/v1/settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_livez_readyz_metrics():
    assert client.get("/livez").status_code == 200
    assert client.get("/readyz").status_code in {200, 503}
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "iems_http_requests_total" in metrics.text or "iems_app_up" in metrics.text


def test_security_headers_present():
    r = client.get("/livez")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_dashboard_static_assets_served():
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "/static/dashboard.css" in page.text
    assert "/static/dashboard.js" in page.text
    assert client.get("/static/dashboard.css").status_code == 200
    assert client.get("/static/dashboard.js").status_code == 200
