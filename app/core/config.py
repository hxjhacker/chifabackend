from __future__ import annotations

import os

from app.config import settings


def _env(name: str, fallback: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        value = os.environ.get(name)
    return str(value if value is not None else fallback).strip()


QUICK_LIVRAISON_API_URL: str = (
    _env("QUICK_LIVRAISON_API_URL", settings.quick_livraison_api_url) or "https://clients.quicklivraison.ma/api"
).rstrip("/")
QUICK_LIVRAISON_API_KEY: str = _env("QUICK_LIVRAISON_API_KEY", settings.quick_livraison_api_key)
FORCELOG_API_URL: str = (_env("FORCELOG_API_URL", settings.forcelog_api_url) or "https://api.forcelog.ma").rstrip("/")
FORCELOG_API_KEY: str = _env("FORCELOG_API_KEY", settings.forcelog_api_key)
