"""RFC 6238 TOTP helpers (NFR-SEC-01) — no external OTP dependency."""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time


def normalize_secret(secret: str) -> bytes:
    padded = secret.strip().replace(" ", "").upper()
    missing = (-len(padded)) % 8
    if missing:
        padded += "=" * missing
    return base64.b32decode(padded, casefold=True)


def totp(
    secret: str,
    *,
    for_time: float | None = None,
    step_seconds: int = 30,
    digits: int = 6,
) -> str:
    key = normalize_secret(secret)
    counter = int((for_time if for_time is not None else time.time()) // step_seconds)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    code = code_int % (10**digits)
    return str(code).zfill(digits)


def verify_totp(
    secret: str,
    code: str,
    *,
    for_time: float | None = None,
    step_seconds: int = 30,
    window: int = 1,
) -> bool:
    if not code or not code.isdigit():
        return False
    now = for_time if for_time is not None else time.time()
    for skew in range(-window, window + 1):
        expected = totp(secret, for_time=now + skew * step_seconds, step_seconds=step_seconds)
        if hmac.compare_digest(expected, code.strip()):
            return True
    return False
