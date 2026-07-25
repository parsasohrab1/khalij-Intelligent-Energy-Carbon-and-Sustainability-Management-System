"""NFR-SEC-01 — authentication with RBAC + 2FA."""

from fastapi import APIRouter, HTTPException, status

from app.schemas import LoginRequest, TokenResponse
from app.services.auth import authenticate

router = APIRouter(prefix="/auth", tags=["auth"])


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
