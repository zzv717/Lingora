"""Password hashing (scrypt from stdlib — no fragile native deps) and JWT helpers."""
import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
import uuid

import jwt

from app.core.config import settings

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P, base64.b64encode(salt + dk).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, blob = stored.split("$")
        data = base64.b64decode(blob)
        salt, expected = data[:16], data[16:]
        dk = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def _decode(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return _encode({
        "sub": user_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "jti": uuid.uuid4().hex,
    })


def create_refresh_token(user_id: str) -> tuple[str, str, datetime]:
    """Returns (token, sha256_hash, expires_at). Only the hash is persisted."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=settings.refresh_token_expire_days)
    token = _encode({"sub": user_id, "type": "refresh", "iat": now, "exp": expires, "jti": uuid.uuid4().hex})
    return token, hashlib.sha256(token.encode()).hexdigest(), expires


def decode_token(token: str, expected_type: Literal["access", "refresh"]) -> dict[str, Any]:
    payload = _decode(token)
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
