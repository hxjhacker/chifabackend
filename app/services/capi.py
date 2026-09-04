from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.models import Order
from app.services.cities import city_latin
from app.services.hashing import hash_city, hash_email, hash_name_parts, hash_phone_digits, sha256_hex
from app.services.phone import phone_digits_for_hash
from app.services.pricing import cents_to_mad


def purchase_event_id(order_id: Any, kind: str = "order") -> str:
    return f"order_{order_id}"


@dataclass
class CapiUser:
    phone_e164: str | None = None
    full_name: str | None = None
    city: str | None = None
    email: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    fbp: str | None = None
    fbc: str | None = None
    ttclid: str | None = None
    sccid: str | None = None
    event_source_url: str = ""

    @classmethod
    def from_order(cls, order: Order) -> "CapiUser":
        return cls(
            phone_e164=order.phone,
            full_name=order.full_name,
            city=order.city,
            client_ip=order.client_ip,
            user_agent=order.user_agent,
            fbp=order.fbp,
            fbc=order.fbc,
            ttclid=order.ttclid,
            sccid=order.sccid,
            event_source_url=order.landing_url or settings.site_url,
        )


def _hashes(user: CapiUser) -> dict[str, str | None]:
    ph = None
    if user.phone_e164:
        ph = hash_phone_digits(phone_digits_for_hash(user.phone_e164))
    fn = ln = None
    if user.full_name:
        fn, ln = hash_name_parts(user.full_name)
    return {
        "ph": ph,
        "fn": fn,
        "ln": ln,
        "ct": hash_city(city_latin(user.city)) if user.city else None,
        "em": hash_email(user.email),
        "country": sha256_hex("ma"),
    }


def order_contents(order: Order) -> tuple[list[str], list[dict[str, Any]], float]:
    ids = [order.product_slug]
    contents = [
        {
            "id": order.product_slug,
            "quantity": order.tier_qty,
            "item_price": cents_to_mad(order.tier_price_cents // max(order.tier_qty, 1)),
        }
    ]
    if order.cross_sell_slug:
        ids.append(order.cross_sell_slug)
        contents.append({"id": order.cross_sell_slug, "quantity": 1, "item_price": 199.0})
    if order.upsell_slug:
        ids.append(order.upsell_slug)
        contents.append({"id": order.upsell_slug, "quantity": 1, "item_price": 99.0})
    return ids, contents, cents_to_mad(order.total_cents)


async def send_purchase(order: Order, event_id: str) -> None:
    ids, contents, value = order_contents(order)
    await dispatch_capi(
        event_name="Purchase",
        event_id=event_id,
        user=CapiUser.from_order(order),
        value=value,
        content_ids=ids,
        contents=contents,
        extra={"order_id": str(order.id)},
    )


async def dispatch_capi(
    *,
    event_name: str,
    event_id: str,
    user: CapiUser,
    value: float | None = None,
    content_ids: list[str] | None = None,
    contents: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    hashes = _hashes(user)
    event_time = int(time.time())
    url = user.event_source_url or settings.site_url
    custom: dict[str, Any] = {
        "currency": "MAD",
        "content_type": "product",
        "content_ids": content_ids or [],
    }
    if value is not None:
        custom["value"] = float(value)
    if contents:
        custom["contents"] = contents
    if extra:
        custom.update(extra)

    async with httpx.AsyncClient(timeout=8.0) as client:
        await _send_meta(client, event_name, event_id, event_time, url, hashes, custom, user)
        await _send_tiktok(client, event_name, event_id, event_time, url, hashes, custom, user)
        await _send_snap(client, event_name, event_id, event_time, url, hashes, custom, user)


def _meta_event(name: str) -> str:
    return {
        "CompletePayment": "Purchase",
        "PURCHASE": "Purchase",
        "Pageview": "PageView",
        "PAGE_VIEW": "PageView",
        "ADD_CART": "AddToCart",
        "START_CHECKOUT": "InitiateCheckout",
        "VIEW_CONTENT": "ViewContent",
    }.get(name, name)


def _tiktok_event(name: str) -> str:
    return {
        "Purchase": "CompletePayment",
        "PURCHASE": "CompletePayment",
        "PageView": "Pageview",
        "PAGE_VIEW": "Pageview",
    }.get(name, name)


def _snap_event(name: str) -> str:
    mapping = {
        "Purchase": "PURCHASE",
        "CompletePayment": "PURCHASE",
        "PageView": "PAGE_VIEW",
        "AddToCart": "ADD_CART",
        "InitiateCheckout": "START_CHECKOUT",
        "ViewContent": "VIEW_CONTENT",
    }
    return mapping.get(name, name.upper())


async def _send_meta(client: httpx.AsyncClient, event_name, event_id, event_time, url, hashes, custom, user: CapiUser) -> None:
    if not settings.meta_pixel_id or not settings.meta_capi_access_token:
        return
    user_data: dict[str, Any] = {"country": [hashes["country"]]}
    for key in ("ph", "fn", "ln", "ct", "em"):
        if hashes.get(key):
            user_data[key] = [hashes[key]]
    if user.client_ip:
        user_data["client_ip_address"] = user.client_ip
    if user.user_agent:
        user_data["client_user_agent"] = user.user_agent
    if user.fbp:
        user_data["fbp"] = user.fbp
    if user.fbc:
        user_data["fbc"] = user.fbc

    payload: dict[str, Any] = {
        "data": [
            {
                "event_name": _meta_event(event_name),
                "event_time": event_time,
                "event_id": event_id,
                "event_source_url": url,
                "action_source": "website",
                "user_data": user_data,
                "custom_data": custom,
            }
        ],
        "access_token": settings.meta_capi_access_token,
    }
    if settings.meta_test_event_code:
        payload["test_event_code"] = settings.meta_test_event_code
    try:
        await client.post(
            f"https://graph.facebook.com/v21.0/{settings.meta_pixel_id}/events",
            json=payload,
        )
    except httpx.HTTPError:
        return


async def _send_tiktok(client: httpx.AsyncClient, event_name, event_id, event_time, url, hashes, custom, user: CapiUser) -> None:
    if not settings.tiktok_pixel_id or not settings.tiktok_access_token:
        return
    person: dict[str, Any] = {}
    if hashes.get("ph"):
        person["phone"] = hashes["ph"]
    if hashes.get("em"):
        person["email"] = hashes["em"]
    if user.client_ip:
        person["ip"] = user.client_ip
    if user.user_agent:
        person["user_agent"] = user.user_agent
    if user.ttclid:
        person["ttclid"] = user.ttclid

    payload = {
        "event_source": "web",
        "event_source_id": settings.tiktok_pixel_id,
        "data": [
            {
                "event": _tiktok_event(event_name),
                "event_time": event_time,
                "event_id": event_id,
                "user": person,
                "properties": {
                    "currency": custom.get("currency", "MAD"),
                    "value": custom.get("value"),
                    "content_ids": custom.get("content_ids", []),
                    "content_type": "product",
                },
                "page": {"url": url},
            }
        ],
    }
    try:
        await client.post(
            "https://business-api.tiktok.com/open_api/v1.3/event/track/",
            json=payload,
            headers={
                "Access-Token": settings.tiktok_access_token,
                "Content-Type": "application/json",
            },
        )
    except httpx.HTTPError:
        return


async def _send_snap(client: httpx.AsyncClient, event_name, event_id, event_time, url, hashes, custom, user: CapiUser) -> None:
    if not settings.snapchat_pixel_id or not settings.snapchat_capi_token:
        return
    user_data: dict[str, Any] = {}
    if hashes.get("ph"):
        user_data["ph"] = [hashes["ph"]]
    if hashes.get("em"):
        user_data["em"] = [hashes["em"]]
    if user.client_ip:
        user_data["client_ip_address"] = user.client_ip
    if user.user_agent:
        user_data["client_user_agent"] = user.user_agent
    if user.sccid:
        user_data["sc_click_id"] = user.sccid

    value = custom.get("value")
    payload = {
        "data": [
            {
                "event_name": _snap_event(event_name),
                "event_time": event_time,
                "event_source_url": url,
                "action_source": "WEB",
                "event_id": event_id,
                "client_dedup_id": event_id,
                "user_data": user_data,
                "custom_data": {
                    "currency": "MAD",
                    "value": f"{float(value):.2f}" if value is not None else "0.00",
                    "content_ids": custom.get("content_ids", []),
                },
            }
        ]
    }
    try:
        await client.post(
            f"https://tr.snapchat.com/v3/{settings.snapchat_pixel_id}/events",
            params={"access_token": settings.snapchat_capi_token},
            json=payload,
        )
    except httpx.HTTPError:
        return


send_purchase = send_purchase
dispatch_capi = dispatch_capi
