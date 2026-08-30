from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from typing import Any

import bcrypt
import jwt

from app.config import settings

COOKIE_NAME = "cg_admin"
JWT_ALG = "HS256"

# Known-valid bcrypt hash (password "secret") so unknown usernames still pay the check cost.
_DUMMY_HASH = b"$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"


def _utf8(value: str) -> bytes:
    return value.encode("utf-8")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_utf8(plain), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _stored_hash() -> bytes | None:
    raw = (settings.admin_password_hash or "").strip()
    if raw:
        return raw.encode("utf-8")
    return None


def password_configured() -> bool:
    return bool((settings.admin_password_hash or "").strip() or (settings.admin_password or "").strip())


def admin_configured() -> bool:
    user = (settings.admin_username or "").strip()
    secret = (settings.admin_jwt_secret or "").strip()
    return bool(user) and password_configured() and len(secret) >= 16


def verify_password(plain: str) -> bool:
    hashed = _stored_hash()
    bootstrap = (settings.admin_password or "").strip()
    if hashed:
        try:
            if bcrypt.checkpw(_utf8(plain), hashed):
                return True
        except ValueError:
            pass
        if not bootstrap:
            return False
    if not bootstrap:
        _dummy_check(plain)
        return False
    if len(plain) != len(bootstrap):
        return False
    return compare_digest(plain, bootstrap)


def _dummy_check(plain: str) -> None:
    try:
        bcrypt.checkpw(_utf8(plain or "x"), _DUMMY_HASH)
    except ValueError:
        pass


def verify_credentials(username: str, password: str) -> bool:
    expected_user = (settings.admin_username or "").strip()
    if not expected_user or not password_configured():
        _dummy_check(password)
        return False

    user_ok = username == expected_user
    if not user_ok:
        _dummy_check(password)
        return False
    return verify_password(password)


def create_access_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": username,
        "role": "admin",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.admin_jwt_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.admin_jwt_secret, algorithm=JWT_ALG)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.admin_jwt_secret, algorithms=[JWT_ALG])


def cookie_secure() -> bool:
    if settings.app_env.lower() in {"development", "dev", "local"}:
        return False
    return settings.site_url.lower().startswith("https://")


def apply_auth_cookie(response: Any, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=settings.admin_jwt_hours * 3600,
        httponly=True,
        secure=cookie_secure(),
        samesite="strict",
        path="/",
    )


def clear_auth_cookie(response: Any) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/", httponly=True, samesite="strict", secure=cookie_secure())
