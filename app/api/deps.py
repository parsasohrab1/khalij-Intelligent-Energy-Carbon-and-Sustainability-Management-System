"""FastAPI auth dependencies for RBAC + settings 2FA."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from app.core.config import get_settings
from app.services.auth import (
    CurrentUser,
    Role,
    role_allows,
    verify_settings_2fa,
    verify_token,
)


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


async def get_current_user_optional(
    authorization: str | None = Header(default=None),
) -> CurrentUser | None:
    token = _extract_bearer(authorization)
    if not token:
        return None
    result = verify_token(token)
    if not result.ok or result.role is None or result.username is None:
        return None
    return CurrentUser(username=result.username, role=result.role, token=token)


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    settings = get_settings()
    token = _extract_bearer(authorization)
    if not token:
        if not settings.auth_enforce:
            # Dev bypass identity
            return CurrentUser(username="dev", role=Role.ADMIN, token="dev")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    result = verify_token(token)
    if not result.ok or result.role is None or result.username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result.detail or "Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return CurrentUser(username=result.username, role=result.role, token=token)


def require_action(action: str):
    async def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        settings = get_settings()
        if not settings.auth_enforce and user.username == "dev":
            return user
        if not role_allows(user.role, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' cannot perform '{action}'",
            )
        return user

    return _dep


def require_settings_admin(
    user: CurrentUser = Depends(require_action("settings")),
    x_2fa_code: str | None = Header(default=None, alias="X-2FA-Code"),
) -> CurrentUser:
    """Admin settings changes require a fresh TOTP code (NFR-SEC-01)."""
    settings = get_settings()
    if not settings.auth_enforce and user.username == "dev":
        return user
    if not verify_settings_2fa(user.username, x_2fa_code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid X-2FA-Code header required for settings changes",
            headers={"X-Requires-2FA": "true"},
        )
    return user
