"""E7 Operator Product — auth/me, shift report, console markers, severity."""

from fastapi.testclient import TestClient

from app.api.routes.alerts import alert_severity
from app.main import app
from app.services.auth import issue_token, Role

client = TestClient(app)


def test_alert_severity_map():
    assert alert_severity("stream_missing") == "critical"
    assert alert_severity("stream_stale") == "warning"
    assert alert_severity("data_quality") == "warning"


def test_auth_me_dev_bypass():
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["role"] in {"admin", "operator", "viewer"}
    assert "actions" in body
    assert body["actions"]["read"] is True


def test_auth_me_with_viewer_token():
    token = issue_token("viewer", Role.VIEWER)
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "viewer"
    assert body["role"] == "viewer"
    assert body["actions"]["operate"] is False
    assert body["actions"]["predict"] is False


def test_operator_shift_summary():
    r = client.get("/api/v1/operator/shift-summary", params={"plant_code": "olefin"})
    assert r.status_code == 200
    body = r.json()
    assert "checklist" in body
    assert "open_notifications" in body
    assert body["plant"]["plant_code"] == "olefin"


def test_operator_shift_csv():
    r = client.get("/api/v1/operator/shift-report.csv", params={"plant_code": "olefin"})
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    assert "plant_code" in r.text


def test_dashboard_has_e7_markers():
    r = client.get("/dashboard")
    assert r.status_code == 200
    text = r.text
    assert "manifest.webmanifest" in text
    assert 'data-require="predict"' in text
    assert 'id="notifBadge"' in text
    assert 'id="reportsBody"' in text
    assert 'id="btnShiftCsv"' in text
    assert 'id="shiftStrip"' in text


def test_pwa_assets_served():
    assert client.get("/static/manifest.webmanifest").status_code == 200
    assert client.get("/static/sw.js").status_code == 200
    assert client.get("/static/icon.svg").status_code == 200
