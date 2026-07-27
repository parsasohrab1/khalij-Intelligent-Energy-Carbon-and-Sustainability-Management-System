"""NFR-SEC-01 / E11 — authentication with RBAC, 2FA, and OIDC IdP."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.schemas import LoginRequest, MeResponse, TokenResponse
from app.services.auth import CurrentUser, authenticate, role_allows
from app.services.oidc import (
    OidcError,
    begin_login_discovered,
    dev_login,
    exchange_code,
    oidc_status,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class OidcDevLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    role: str = Field(default="operator", pattern="^(viewer|operator|admin)$")


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    result = authenticate(body.username, body.password, body.totp_code)
    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result.detail,
            headers={"X-Requires-2FA": "true"} if result.requires_2fa else None,
        )
    assert result.token is not None and result.role is not None
    return TokenResponse(
        access_token=result.token,
        role=result.role.value,
        requires_2fa=result.requires_2fa,
    )


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    """E7 — current operator identity + allowed actions for UI gating."""
    actions = {
        action: role_allows(user.role, action)
        for action in ("read", "predict", "operate", "train", "apply", "settings")
    }
    return MeResponse(username=user.username, role=user.role.value, actions=actions)


@router.get("/oidc/status")
async def get_oidc_status() -> dict[str, Any]:
    return oidc_status()


@router.get("/oidc/login")
async def oidc_login() -> RedirectResponse:
    settings = get_settings()
    if not settings.oidc_enabled:
        raise HTTPException(status_code=404, detail="OIDC disabled")
    try:
        url, _state = await begin_login_discovered(settings)
    except OidcError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=url, status_code=302)


@router.get("/oidc/callback")
async def oidc_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> TokenResponse:
    settings = get_settings()
    if not settings.oidc_enabled:
        raise HTTPException(status_code=404, detail="OIDC disabled")
    try:
        result = await exchange_code(code, state, settings=settings)
    except OidcError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    assert result.token is not None and result.role is not None
    return TokenResponse(
        access_token=result.token,
        role=result.role.value,
        requires_2fa=False,
    )


@router.post("/oidc/dev-login", response_model=TokenResponse)
async def oidc_dev_login(body: OidcDevLoginRequest) -> TokenResponse:
    """E11 — local IdP stand-in (APP_DEBUG + OIDC_DEV_BYPASS only)."""
    try:
        result = dev_login(body.username, body.role)
    except OidcError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    assert result.token is not None and result.role is not None
    return TokenResponse(
        access_token=result.token,
        role=result.role.value,
        requires_2fa=False,
    )
