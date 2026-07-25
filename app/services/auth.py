"""NFR-SEC-01 — RBAC, hashed passwords, TOTP 2FA, signed tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from enum import Enum

from app.core.config import get_settings
from app.security.totp import verify_totp

# Demo TOTP secret (base32) — replace via IdP in production
DEMO_TOTP_SECRET = "JBSWY3DPEHPK3PXP"


class Role(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


def hash_password(password: str, salt: str | None = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    salt_b = bytes.fromhex(salt)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_b, 120_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, salt, digest = encoded.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        candidate = hash_password(password, salt=salt)
        return hmac.compare_digest(candidate, encoded)
    except ValueError:
        return False


def _bootstrap_users() -> dict[str, dict]:
    # Stable salts for deterministic test/dev credentials
    return {
        "viewer": {
            "password_hash": hash_password("viewer", salt="11" * 16),
            "role": Role.VIEWER,
            "totp_secret": None,
        },
        "operator": {
            "password_hash": hash_password("operator", salt="22" * 16),
            "role": Role.OPERATOR,
            "totp_secret": DEMO_TOTP_SECRET,
        },
        "admin": {
            "password_hash": hash_password("admin", salt="33" * 16),
            "role": Role.ADMIN,
            "totp_secret": DEMO_TOTP_SECRET,
        },
    }


_USERS: dict[str, dict] = _bootstrap_users()


@dataclass
class AuthResult:
    ok: bool
    username: str | None = None
    role: Role | None = None
    requires_2fa: bool = False
    token: str | None = None
    detail: str = ""


@dataclass
class CurrentUser:
    username: str
    role: Role
    token: str


def _sign(payload: str) -> str:
    secret = get_settings().secret_key.encode()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def issue_token(username: str, role: Role, ttl_seconds: int | None = None) -> str:
    ttl = ttl_seconds or get_settings().auth_token_ttl_seconds
    exp = int(time.time()) + ttl
    body = f"{username}:{role.value}:{exp}"
    return f"{body}:{_sign(body)}"


def verify_token(token: str) -> AuthResult:
    try:
        username, role_s, exp_s, sig = token.split(":", 3)
        body = f"{username}:{role_s}:{exp_s}"
        if not hmac.compare_digest(_sign(body), sig):
            return AuthResult(ok=False, detail="Invalid token signature")
        if int(exp_s) < int(time.time()):
            return AuthResult(ok=False, detail="Token expired")
        return AuthResult(
            ok=True,
            username=username,
            role=Role(role_s),
            token=token,
        )
    except (ValueError, KeyError):
        return AuthResult(ok=False, detail="Malformed token")


def authenticate(
    username: str,
    password: str,
    totp_code: str | None = None,
    *,
    require_2fa: bool = False,
) -> AuthResult:
    user = _USERS.get(username)
    if not user or not verify_password(password, user["password_hash"]):
        return AuthResult(ok=False, detail="Invalid credentials")

    role: Role = user["role"]
    has_totp = user.get("totp_secret") is not None
    # Login: operator/admin may skip TOTP unless require_2fa (settings path)
    needs_2fa = has_totp and (require_2fa or get_settings().auth_login_require_2fa)

    if needs_2fa:
        if not totp_code:
            return AuthResult(
                ok=False,
                username=username,
                role=role,
                requires_2fa=True,
                detail="2FA required",
            )
        if not verify_totp(user["totp_secret"], totp_code):
            return AuthResult(
                ok=False,
                username=username,
                role=role,
                requires_2fa=True,
                detail="Invalid 2FA code",
            )

    token = issue_token(username, role)
    return AuthResult(
        ok=True,
        username=username,
        role=role,
        requires_2fa=has_totp,
        token=token,
    )


def verify_settings_2fa(username: str, totp_code: str | None) -> bool:
    user = _USERS.get(username)
    if user is None:
        return False
    secret = user.get("totp_secret")
    if secret is None:
        return True  # viewers have no settings access anyway
    if not totp_code:
        return False
    return verify_totp(secret, totp_code)


def role_allows(role: Role, action: str) -> bool:
    matrix = {
        "read": {Role.VIEWER, Role.OPERATOR, Role.ADMIN},
        "predict": {Role.OPERATOR, Role.ADMIN},
        "operate": {Role.OPERATOR, Role.ADMIN},
        "train": {Role.OPERATOR, Role.ADMIN},
        "settings": {Role.ADMIN},
    }
    return role in matrix.get(action, set())
