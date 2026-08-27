from __future__ import annotations

import ipaddress
import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_INSIGHTS = "https://geoip.maxmind.com/geoip/v2.1/insights/{ip}"
_COUNTRY = "https://geoip.maxmind.com/geoip/v2.1/country/{ip}"
_BLOCK_TRAITS = (
    "is_anonymous",
    "is_anonymous_vpn",
    "is_hosting_provider",
    "is_public_proxy",
    "is_residential_proxy",
    "is_tor_exit_node",
)
_BLOCK_USER_TYPES = {"hosting", "tor", "vpn", "proxy"}


def _is_public_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def _lookup(ip: str) -> dict | None:
    auth = (settings.maxmind_account_id, settings.maxmind_license_key)
    for url in (_INSIGHTS.format(ip=ip), _COUNTRY.format(ip=ip)):
        try:
            response = httpx.get(url, auth=auth, timeout=2.5)
        except httpx.HTTPError:
            log.warning("maxmind request failed url=%s", url)
            continue
        if response.status_code == 200:
            return response.json()
        if response.status_code in {401, 402, 403}:
            continue
        log.warning("maxmind status=%s url=%s", response.status_code, url)
        return None
    return None


def ip_is_blocked(ip: str) -> bool:
    """True when MaxMind says the IP is risky. Fail-open on missing creds or errors."""
    if not settings.enable_ip_fraud_check:
        return False
    if not settings.maxmind_account_id or not settings.maxmind_license_key:
        return False
    if not ip or not _is_public_ip(ip):
        return False

    data = _lookup(ip)
    if not data:
        return False

    country = ((data.get("country") or {}).get("iso_code") or "").upper()
    if country and country != "MA":
        return True

    traits = data.get("traits") or {}
    if any(traits.get(key) for key in _BLOCK_TRAITS):
        return True
    user_type = (traits.get("user_type") or "").lower()
    return user_type in _BLOCK_USER_TYPES
