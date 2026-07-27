"""E11 — OIDC IdP integration (login redirect + callback + role mapping)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings, get_settings
from app.services.auth import AuthResult, Role, issue_token

logger = logging.getLogger(__name__)

# In-memory PKCE / state store for single-process demos (replace with Redis in HA)
_pending_states: dict[str, dict[str, str]] = {}


@dataclass
class OidcDiscovery:
    authorization_endpoint: str
    token_endpoint: str
    issuer: str


class OidcError(RuntimeError):
    """OIDC flow failure."""


def _split_csv(value: str) -> set[str]:
    return {v.strip().lower() for v in value.split(",") if v.strip()}


def map_roles_from_claims(claims: dict[str, Any], settings: Settings | None = None) -> Role:
    cfg = settings or get_settings()
    raw = claims.get(cfg.oidc_role_claim) or claims.get("groups") or claims.get("realm_access", {}).get("roles")
    roles: list[str] = []
    if isinstance(raw, str):
        roles = [raw]
    elif isinstance(raw, list):
        roles = [str(x) for x in raw]
    elif isinstance(raw, dict) and "roles" in raw:
        roles = [str(x) for x in raw["roles"]]
    normalized = {r.lower() for r in roles}
    if normalized & _split_csv(cfg.oidc_admin_roles):
        return Role.ADMIN
    if normalized & _split_csv(cfg.oidc_operator_roles):
        return Role.OPERATOR
    if normalized & _split_csv(cfg.oidc_viewer_roles):
        return Role.VIEWER
    return Role.VIEWER


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode JWT payload without signature verify (IdP already authenticated the token response)."""
    parts = token.split(".")
    if len(parts) < 2:
        raise OidcError("Malformed JWT")
    return json.loads(_b64url_decode(parts[1]).decode("utf-8"))


async def discover(settings: Settings | None = None) -> OidcDiscovery:
    cfg = settings or get_settings()
    if not cfg.oidc_issuer:
        raise OidcError("OIDC_ISSUER is required when OIDC is enabled")
    url = cfg.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return OidcDiscovery(
        authorization_endpoint=str(data["authorization_endpoint"]),
        token_endpoint=str(data["token_endpoint"]),
        issuer=str(data.get("issuer") or cfg.oidc_issuer),
    )


def begin_login(settings: Settings | None = None) -> tuple[str, str]:
    """Return (authorize_url, state)."""
    cfg = settings or get_settings()
    if not cfg.oidc_enabled:
        raise OidcError("OIDC is disabled")
    if not cfg.oidc_issuer or not cfg.oidc_client_id:
        raise OidcError("OIDC_ISSUER and OIDC_CLIENT_ID required")

    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    _pending_states[state] = {"verifier": verifier}

    # Prefer async discovery in route; sync fallback builds authorize from issuer
    auth_base = cfg.oidc_issuer.rstrip("/") + "/protocol/openid-connect/auth"
    # Keycloak-style default; overridden when discovery succeeds in async path
    params = {
        "response_type": "code",
        "client_id": cfg.oidc_client_id,
        "redirect_uri": cfg.oidc_redirect_uri,
        "scope": cfg.oidc_scopes,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{auth_base}?{urlencode(params)}", state


async def begin_login_discovered(settings: Settings | None = None) -> tuple[str, str]:
    cfg = settings or get_settings()
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    _pending_states[state] = {"verifier": verifier}
    try:
        disc = await discover(cfg)
        auth_base = disc.authorization_endpoint
    except Exception:
        logger.exception("OIDC discovery failed; using Keycloak-style authorize path")
        auth_base = cfg.oidc_issuer.rstrip("/") + "/protocol/openid-connect/auth"
    params = {
        "response_type": "code",
        "client_id": cfg.oidc_client_id,
        "redirect_uri": cfg.oidc_redirect_uri,
        "scope": cfg.oidc_scopes,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{auth_base}?{urlencode(params)}", state


async def exchange_code(
    code: str,
    state: str,
    *,
    settings: Settings | None = None,
) -> AuthResult:
    cfg = settings or get_settings()
    pending = _pending_states.pop(state, None)
    if pending is None:
        raise OidcError("Invalid or expired OIDC state")
    verifier = pending["verifier"]

    try:
        disc = await discover(cfg)
        token_url = disc.token_endpoint
    except Exception as exc:
        raise OidcError(f"OIDC discovery failed: {exc}") from exc

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg.oidc_redirect_uri,
        "client_id": cfg.oidc_client_id,
        "code_verifier": verifier,
    }
    auth = None
    if cfg.oidc_client_secret:
        auth = (cfg.oidc_client_id, cfg.oidc_client_secret)

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(token_url, data=data, auth=auth)
        if resp.status_code >= 400:
            raise OidcError(f"Token exchange failed: HTTP {resp.status_code}")
        body = resp.json()

    id_token = body.get("id_token") or body.get("access_token")
    if not id_token:
        raise OidcError("No id_token/access_token in token response")
    claims = decode_jwt_payload(id_token)
    username = str(
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("sub")
        or "oidc-user"
    )
    role = map_roles_from_claims(claims, cfg)
    token = issue_token(username, role)
    return AuthResult(ok=True, username=username, role=role, token=token)


def dev_login(username: str, role: str, *, settings: Settings | None = None) -> AuthResult:
    """Local IdP stand-in for APP_DEBUG + OIDC_DEV_BYPASS."""
    cfg = settings or get_settings()
    if not (cfg.oidc_enabled and cfg.oidc_dev_bypass and cfg.app_debug):
        raise OidcError("OIDC dev login disabled")
    try:
        mapped = Role(role.lower())
    except ValueError as exc:
        raise OidcError("role must be viewer|operator|admin") from exc
    token = issue_token(username, mapped)
    return AuthResult(ok=True, username=username, role=mapped, token=token)


def oidc_status(settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    return {
        "enabled": cfg.oidc_enabled,
        "issuer": cfg.oidc_issuer or None,
        "client_id": cfg.oidc_client_id or None,
        "redirect_uri": cfg.oidc_redirect_uri,
        "dev_bypass": bool(cfg.oidc_dev_bypass and cfg.app_debug),
        "role_claim": cfg.oidc_role_claim,
    }
