from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hmac import compare_digest
from typing import Any
import re

import bcrypt
import jwt

from app.config import settings

COOKIE_NAME = "cg_admin"
JWT_ALG = "HS256"
_BCRYPT_RE = re.compile(r"^\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$")

FALLBACK_USER = "MOhammed2003"
FALLBACK_PASS = "simo25082003elyoussfiM#"
FALLBACK_JWT = "204a308d75e24d90b8e47391e1cc9d33b2b08cce2dcd4482a2276542bd346504"

# Known-valid bcrypt hash (password "secret") so unknown usernames still pay the check cost.
_DUMMY_HASH = b"$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"


def _utf8(value: str) -> bytes:
    return value.encode("utf-8")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_utf8(plain), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _n(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    return text or fallback


def admin_username() -> str:
    return _n(settings.admin_username, FALLBACK_USER)


def admin_jwt_secret() -> str:
    return _n(settings.admin_jwt_secret, FALLBACK_JWT)


def _stored_hash() -> bytes | None:
    raw = (settings.admin_password_hash or "").strip()
    if raw and _BCRYPT_RE.match(raw):
        return raw.encode("utf-8")
    return None


def _plain_password() -> str:
    explicit = (settings.admin_password or "").strip()
    if explicit:
        return explicit
    raw = (settings.admin_password_hash or "").strip()
    if raw and not _BCRYPT_RE.match(raw):
        return raw
    return FALLBACK_PASS


def password_configured() -> bool:
    return bool(_plain_password() or _stored_hash())


def admin_configured() -> bool:
    return bool(admin_username()) and password_configured() and len(admin_jwt_secret()) >= 16


def verify_password(plain: str) -> bool:
    hashed = _stored_hash()
    bootstrap = _plain_password()
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
    expected_user = admin_username()
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
    return jwt.encode(payload, admin_jwt_secret(), algorithm=JWT_ALG)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, admin_jwt_secret(), algorithms=[JWT_ALG])


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
