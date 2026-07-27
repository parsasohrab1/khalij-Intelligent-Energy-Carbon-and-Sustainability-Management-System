"""E9 Advisory→Action — write allowlist, workflow gates, RBAC apply."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.ingestion.opcua_write import WriteNotAllowedError, plan_setpoint_writes, write_setpoints
from app.ingestion.tag_map import reload_tag_map
from app.main import app
from app.optimization.apply import ActionWorkflowError
from app.services.auth import Role, issue_token, role_allows

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    monkeypatch.setenv("OPC_WRITE_ENABLED", "false")
    monkeypatch.setenv("OPC_WRITE_DRY_RUN_DEFAULT", "true")
    monkeypatch.setenv("OPT_REQUIRE_SIM_BEFORE_APPLY", "true")
    get_settings.cache_clear()
    reload_tag_map()
    yield
    get_settings.cache_clear()
    reload_tag_map()


def test_role_apply_is_admin_only():
    assert role_allows(Role.ADMIN, "apply")
    assert not role_allows(Role.OPERATOR, "apply")
    assert not role_allows(Role.VIEWER, "apply")


def test_auth_me_includes_apply_action():
    token = issue_token("admin", Role.ADMIN)
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["actions"]["apply"] is True

    op = issue_token("operator", Role.OPERATOR)
    r2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {op}"})
    assert r2.json()["actions"]["apply"] is False


def test_writable_setpoint_plan_allowlist():
    plan = plan_setpoint_writes(
        "olefin",
        {
            "reactor_temp_c": 390.0,
            "feed_flow_tonh": 110.0,
            "fuel_gas_flow_km3h": 95.0,  # not writable
        },
    )
    fields = {p.field for p in plan.planned}
    assert "reactor_temp_c" in fields
    assert "feed_flow_tonh" in fields
    assert "fuel_gas_flow_km3h" not in fields
    assert any("fuel_gas" in s for s in plan.skipped)
    assert all(p.node_id.endswith("_SP_C") or "SP" in p.node_id for p in plan.planned)


@pytest.mark.asyncio
async def test_live_write_blocked_without_flag():
    with pytest.raises(WriteNotAllowedError, match="OPC_WRITE_ENABLED"):
        await write_setpoints(
            "olefin",
            {"reactor_temp_c": 390.0},
            dry_run=False,
        )


@pytest.mark.asyncio
async def test_dry_run_write_returns_plan():
    result = await write_setpoints(
        "olefin",
        {"reactor_temp_c": 390.0, "feed_flow_tonh": 108.0},
        dry_run=True,
    )
    assert result.dry_run is True
    assert len(result.planned) == 2
    assert result.written == []


def test_dashboard_has_e9_markers():
    r = client.get("/dashboard")
    assert r.status_code == 200
    text = r.text
    assert "E9 Action" in text or "approve" in client.get("/static/dashboard.js").text
    js = client.get("/static/dashboard.js").text
    assert "data-apr=" in js
    assert "data-apl=" in js
    assert "data-imp=" in js
    assert "data-aud=" in js
    assert 'data-require="apply"' in js


def test_action_workflow_error_message():
    err = ActionWorkflowError("Approve requires status=accepted (current=pending)")
    assert "accepted" in str(err)
