from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, select

from app.config import settings
from app.models import Order, OrderItem
from app.services.cities import CITIES

BATCH_LIMIT = 200
CARRIER = "gooli"
CREATE_URL = "/api_orders.php?action=create"
MAX_SKEW_SEC = 5 * 60
PACK_NAMES = {
    "quran": "USB القرآن",
    "taalim": "USB التعليمي",
    "music": "USB الموسيقى",
    "zit_alfasokh": "زيت الفسوخ",
    "alkhatm_alrijali": "الخاتم الرجالي",
    "almisk_alabyad": "المسك الأبيض",
    "kids": "USB تعليم الأطفال",
    "educative": "الفلاشة التعليمية الذكية",
    "extra": "مفتاح إضافي بسعر العرض",
    "pack-royal-power": "الباك الملكي المتكامل",
    "pack-royal": "الباك الملكي المتكامل",
}


def api_key() -> str:
    return str(settings.gooli_api_key or "").strip().strip("'\"")


def webhook_secret() -> str:
    secret = str(settings.gooli_webhook_secret or "").strip().strip("'\"")
    return secret or api_key()


def api_base() -> str:
    return (str(settings.gooli_api_base or "https://gooli.pro").strip() or "https://gooli.pro").rstrip("/")


def configured() -> bool:
    return bool(api_key())


def external_ref(order_id: str) -> str:
    compact = str(order_id or "").replace("-", "")
    return f"CFG-{compact[:6].upper()}"


def _fold(value: str) -> str:
    text_value = unicodedata.normalize("NFKD", value or "")
    text_value = "".join(ch for ch in text_value if not unicodedata.combining(ch))
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"), ("ى", "ي"), ("ة", "ه")):
        text_value = text_value.replace(src, dst)
    text_value = text_value.casefold()
    text_value = re.sub(r"[^\w\s]+", " ", text_value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text_value).strip()


def to_gooli_city(raw: str | None) -> str | None:
    needle = _fold(str(raw or ""))
    if len(needle) < 2:
        return None
    for city in CITIES:
        names = [str(city.get("ar") or ""), str(city.get("fr") or "")]
        names.extend(str(alias) for alias in city.get("aliases") or [])
        if any(_fold(name) == needle for name in names if name):
            latin = str(city.get("fr") or "").strip()
            if not latin or re.search(r"[\u0600-\u06FF]", latin):
                return None
            return latin
    if len(needle) >= 3:
        for city in CITIES:
            names = [str(city.get("ar") or ""), str(city.get("fr") or "")]
            names.extend(str(alias) for alias in city.get("aliases") or [])
            folded = [_fold(name) for name in names if name]
            if any(len(name) >= 3 and (needle in name or name in needle) for name in folded):
                latin = str(city.get("fr") or "").strip()
                if latin and not re.search(r"[\u0600-\u06FF]", latin):
                    return latin
    if re.search(r"[\u0600-\u06FF]", str(raw or "")):
        return None
    return str(raw or "").strip() or None


def national_phone(raw: str | None) -> str | None:
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("00212"):
        digits = digits[5:]
    if digits.startswith("212") and len(digits) >= 12:
        digits = "0" + digits[3:12]
    elif len(digits) == 9 and digits[:1] in "567":
        digits = "0" + digits
    if len(digits) == 10 and digits.startswith("0") and digits[1:2] in "567":
        return digits
    return None


def _display_status(raw: str) -> str:
    if raw in ("pending", "upsell_accepted", "new"):
        return "new"
    if raw == "in_shipping":
        return "shipped"
    if raw in ("confirmed", "shipped", "delivered", "returned", "cancelled", "out_of_zone"):
        return raw
    return "new"


def _address(order: Order, city: str) -> str:
    stored = str(getattr(order, "address", None) or "").strip()
    if stored:
        return stored
    bits = [str(getattr(order, field, None) or "").strip() for field in ("quartier", "street", "building", "landmark")]
    joined = "، ".join(bit for bit in bits if bit)
    return joined or city


def _products(session: Session, order: Order) -> list[dict[str, Any]]:
    items = session.exec(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    rows: list[dict[str, Any]] = []
    for item in items:
        name = PACK_NAMES.get(str(item.product_slug), str(item.product_slug or "Article"))
        qty = int(item.quantity or 1)
        rows.append({"name": name or "Article", "quantity": qty if qty > 0 else 1})
    if rows:
        return rows
    slug = str(getattr(order, "product_slug", "") or "Article")
    custom = str(getattr(order, "custom_product_name", "") or "").strip()
    qty = int(getattr(order, "tier_qty", 1) or 1)
    return [{"name": custom or PACK_NAMES.get(slug, slug), "quantity": qty if qty > 0 else 1}]


def build_order(session: Session, order: Order) -> dict[str, Any] | dict[str, str]:
    ref = external_ref(str(order.id))
    name = str(order.full_name or "").strip()
    if len(name) < 3:
        return {"error": "اسم المستلم ناقص.", "external_ref": ref, "field": "fullname"}
    phone = national_phone(str(getattr(order, "phone_national", "") or order.phone or ""))
    if not phone:
        return {"error": "رقم الهاتف يجب أن يكون 10 أرقام ويبدأ بـ 05 أو 06 أو 07.", "external_ref": ref, "field": "phone"}
    city = to_gooli_city(str(getattr(order, "shipping_city", None) or order.city or ""))
    if not city:
        label = str(getattr(order, "shipping_city", None) or order.city or "").strip() or "بدون مدينة"
        return {"error": f"المدينة غير مطابقة في Gooli: {label}", "external_ref": ref, "field": "city"}
    cents = int(getattr(order, "total_cents", 0) or 0)
    note = str(getattr(order, "courier_notes", None) or "").strip()
    return {
        "payload": {
            "external_ref": ref,
            "fullname": name,
            "phone": phone,
            "city": city,
            "address": _address(order, city),
            "products": _products(session, order),
            "price": round(cents / 100.0, 2),
            "note": note,
            "open_package": True,
        }
    }


def _rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    found: list[dict[str, Any]] = []
    for key in ("orders", "data", "created", "results", "items"):
        bucket = payload.get(key)
        if isinstance(bucket, list):
            found.extend(item for item in bucket if isinstance(item, dict))
        elif isinstance(bucket, dict) and any(bucket.get(name) for name in ("external_ref", "tracking_code", "errors")):
            found.append(bucket)
    if payload.get("external_ref") or payload.get("tracking_code"):
        found.append(payload)
    return found


def _text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def parse_created(payload: Any) -> list[dict[str, str]]:
    created: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in _rows(payload):
        if isinstance(row.get("errors"), list) and row.get("errors"):
            continue
        ref = _text(row, ("external_ref", "externalRef", "reference", "ref")).lstrip("#")
        tracking = _text(row, ("tracking_code", "trackingCode", "tracking", "code", "barcode", "awb"))
        if not ref or not tracking:
            continue
        key = f"{ref}:{tracking}"
        if key in seen:
            continue
        seen.add(key)
        created.append({"external_ref": ref, "tracking_code": tracking})
    return created


def parse_errors(payload: Any) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []

    def push(value: Any, fallback: str = "") -> None:
        if isinstance(value, str) and value.strip():
            errors.append({"external_ref": fallback, "message": value.strip()})
            return
        if not isinstance(value, dict):
            return
        message = _text(value, ("message", "error", "detail", "msg"))
        field = _text(value, ("field", "attribute", "key"))
        ref = _text(value, ("external_ref", "externalRef", "reference", "ref")) or fallback
        nested = value.get("errors")
        if isinstance(nested, list):
            for item in nested:
                push(item, ref)
        if message:
            errors.append({"external_ref": ref, "field": field, "message": message})

    if isinstance(payload, dict) and isinstance(payload.get("errors"), list):
        for item in payload["errors"]:
            push(item)
    for row in _rows(payload):
        if isinstance(row.get("errors"), list):
            push(row)
    if not errors and isinstance(payload, dict):
        message = _text(payload, ("message", "error", "detail"))
        if message:
            errors.append({"external_ref": "", "field": "", "message": message})
    return errors


def format_errors(errors: list[dict[str, str]]) -> str:
    parts = []
    for error in errors:
        ref = f"{error.get('external_ref')}: " if error.get("external_ref") else ""
        field = f"{error.get('field')} — " if error.get("field") else ""
        message = str(error.get("message") or "").strip()
        if message:
            parts.append(f"{ref}{field}{message}")
    return " · ".join(parts)


def _post(orders: list[dict[str, Any]]) -> tuple[int, Any]:
    response = httpx.post(
        f"{api_base()}{CREATE_URL}",
        headers={"Accept": "application/json", "Content-Type": "application/json", "X-Api-Key": api_key()},
        json={"orders": orders},
        timeout=20.0,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {"message": (response.text or "")[:500]}
    return response.status_code, payload


def _mark_shipped(session: Session, order_id: Any, tracking: str) -> None:
    session.execute(
        text(
            """
            UPDATE orders SET
              status = 'shipped',
              carrier = 'gooli',
              carrier_status = 'Ajouté',
              meta_livraison_code = :code,
              meta_livraison_sent_at = COALESCE(meta_livraison_sent_at, now()),
              dispatched_at = COALESCE(dispatched_at, now()),
              shipped_at = COALESCE(shipped_at, now()),
              confirmed_at = COALESCE(confirmed_at, now()),
              cancelled_at = NULL,
              delivered_at = NULL,
              updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": order_id, "code": tracking[:80]},
    )
    try:
        session.execute(text("SAVEPOINT gooli_payout"))
        session.execute(text("UPDATE orders SET team_payout_paid = false WHERE id = :id"), {"id": order_id})
        session.execute(text("RELEASE SAVEPOINT gooli_payout"))
    except Exception:
        session.execute(text("ROLLBACK TO SAVEPOINT gooli_payout"))


def _load(session: Session, token: str) -> Order | None:
    raw = str(token or "").strip()
    if not raw:
        return None
    try:
        return session.get(Order, UUID(raw))
    except Exception:
        return None


def dispatch_gooli_batch(session: Session, tokens: list[str]) -> dict[str, Any]:
    if not configured():
        raise HTTPException(status_code=400, detail="gooli_not_configured")
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    ready: list[tuple[Order, dict[str, Any]]] = []
    for token in tokens:
        order = _load(session, token)
        if not order:
            results.append({"order_id": token, "success": False, "tracking": "", "error": "الطلبية غير موجودة.", "carrier": CARRIER})
            errors.append({"message": "الطلبية غير موجودة."})
            continue
        ref = external_ref(str(order.id))
        status = _display_status(str(order.status or ""))
        existing = str(getattr(order, "meta_livraison_code", "") or "").strip()
        if status in ("cancelled", "returned"):
            message = "لا يمكن شحن طلبية مرتجعة." if status == "returned" else "لا يمكن شحن طلبية ملغاة."
            results.append({"order_id": str(order.id), "success": False, "tracking": "", "error": message, "carrier": CARRIER})
            errors.append({"external_ref": ref, "message": message})
            continue
        if status not in ("confirmed", "shipped"):
            results.append({"order_id": str(order.id), "success": False, "tracking": "", "error": "الطلبية غير مؤكدة.", "carrier": CARRIER})
            errors.append({"external_ref": ref, "message": "الطلبية غير مؤكدة."})
            continue
        if existing:
            results.append({"order_id": str(order.id), "success": True, "tracking": existing, "error": "", "carrier": CARRIER})
            continue
        built = build_order(session, order)
        if "error" in built:
            results.append({"order_id": str(order.id), "success": False, "tracking": "", "error": built["error"], "carrier": CARRIER})
            errors.append({"external_ref": ref, "field": str(built.get("field") or ""), "message": str(built["error"])})
            continue
        ready.append((order, built["payload"]))

    for start in range(0, len(ready), BATCH_LIMIT):
        group = ready[start : start + BATCH_LIMIT]
        try:
            status_code, payload = _post([row[1] for row in group])
        except Exception as exc:
            message = str(exc) or "تعذر الاتصال بـ Gooli."
            for order, body in group:
                results.append({"order_id": str(order.id), "success": False, "tracking": "", "error": message, "carrier": CARRIER})
                errors.append({"external_ref": body["external_ref"], "message": message})
            continue
        created = {row["external_ref"].upper(): row["tracking_code"] for row in parse_created(payload)}
        remote_errors = parse_errors(payload)
        by_ref: dict[str, list[dict[str, str]]] = {}
        for error in remote_errors:
            by_ref.setdefault(str(error.get("external_ref") or "").lstrip("#").upper(), []).append(error)
        accepted = status_code == 201 or (status_code == 200 and created and not remote_errors)
        for order, body in group:
            tracking = created.get(str(body["external_ref"]).upper(), "")
            if tracking and (accepted or status_code < 400):
                _mark_shipped(session, order.id, tracking)
                results.append({"order_id": str(order.id), "success": True, "tracking": tracking, "error": "", "carrier": CARRIER})
                continue
            matched = by_ref.get(str(body["external_ref"]).upper()) or ([] if by_ref else remote_errors)
            message = format_errors(matched) or f"رفض Gooli الإرسال ({status_code})."
            results.append({"order_id": str(order.id), "success": False, "tracking": "", "error": message, "carrier": CARRIER})
            errors.extend(matched or [{"external_ref": body["external_ref"], "message": message}])
    session.commit()
    success_count = sum(1 for row in results if row.get("success"))
    failed_count = len(results) - success_count
    message = format_errors(errors) or (f"فشل إرسال {failed_count} طلبية إلى Gooli." if failed_count else f"تم إرسال {success_count} طلبية إلى Gooli.")
    return {
        "http_status": 200 if success_count else 422,
        "success_count": success_count,
        "failed_count": failed_count,
        "message": message,
        "errors": errors,
        "results": results,
    }


def map_status(raw: str | None) -> str | None:
    folded = _fold(str(raw or ""))
    if not folded:
        return None
    if any(token in folded for token in ("hors zone", "out of zone", "zone non couverte", "خارج منطقة")):
        return "out_of_zone"
    if any(token in folded for token in ("retour", "returned", "returne", "مرتجع")):
        return "returned"
    if any(token in folded for token in ("annul", "cancel", "refus", "refuse", "ملغ")):
        return "cancelled"
    if any(token in folded for token in ("non livre", "pas livre", "not delivered")):
        return "shipped"
    if any(token in folded for token in ("ajoute", "synced", "sync", "ramass", "exped", "distribution", "livraison", "en cours", "en livraison", "shipped", "اضيف", "تمت الاضاف")):
        return "shipped"
    if re.search(r"(?:^|\s)(livre|livree|delivered)(?:\s|$)", folded) or any(token in folded for token in ("تم التسليم", "تم التوصيل")):
        return "delivered"
    if folded in ("confirmed", "confirme"):
        return "confirmed"
    return None


def _safe_equal(left: str, right: str) -> bool:
    a = left.encode()
    b = right.encode()
    if len(a) != len(b):
        hmac.compare_digest(a, b" " * len(a))
        return False
    return hmac.compare_digest(a, b)


def _digest_matches(secret: str, payload: str, presented: str) -> bool:
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    token = presented.strip()
    if not token:
        return False
    return _safe_equal(mac.hex(), token.lower()) or _safe_equal(_b64(mac), token)


def _b64(raw: bytes) -> str:
    import base64

    return base64.b64encode(raw).decode()


def _epoch(raw: str) -> int | None:
    text_value = str(raw or "").strip()
    if not text_value:
        return None
    if text_value.isdigit():
        num = int(text_value)
        return num // 1000 if num > 10_000_000_000 else num
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(parsed.timestamp())


def verify_signature(raw_body: bytes, signature_header: str, timestamp_header: str, secret: str, now: int | None = None) -> bool:
    secret = secret.strip()
    signature = str(signature_header or "").strip()
    if not secret or not signature:
        return False
    timestamp = ""
    hashes: list[str] = []
    for part in signature.split(","):
        piece = part.strip()
        if not piece:
            continue
        if "=" not in piece:
            hashes.append(re.sub(r"(?i)^sha256=", "", piece))
            continue
        key, value = piece.split("=", 1)
        value = re.sub(r"(?i)^sha256=", "", value.strip())
        if key.strip().lower() in ("t", "ts", "timestamp"):
            timestamp = value
        elif value:
            hashes.append(value)
    if not hashes:
        return False
    if not timestamp:
        timestamp = str(timestamp_header or "").strip()
    if not timestamp:
        try:
            body = json.loads(raw_body.decode() or "{}")
        except Exception:
            body = {}
        if isinstance(body, dict):
            for key in ("timestamp", "sent_at", "created_at", "createdAt"):
                if body.get(key):
                    timestamp = str(body.get(key))
                    break
    stamp = _epoch(timestamp)
    if stamp is None:
        return False
    current = now if now is not None else int(datetime.now(timezone.utc).timestamp())
    if abs(current - stamp) > MAX_SKEW_SEC:
        return False
    raw = raw_body.decode()
    signed = f"{stamp}.{raw}"
    return any(_digest_matches(secret, signed, item) or _digest_matches(secret, raw, item) for item in hashes)


def _find_order(session: Session, external: str, tracking: str) -> Any:
    if tracking:
        rows = session.execute(
            text(
                """
                SELECT id::text AS id, status, carrier, meta_livraison_code
                FROM orders
                WHERE BTRIM(COALESCE(meta_livraison_code, '')) = :tracking
                LIMIT 2
                """
            ),
            {"tracking": tracking},
        ).mappings().all()
        if len(rows) == 1:
            return rows[0]
    if not external:
        return None
    rows = session.execute(
        text(
            """
            SELECT id::text AS id, status, carrier, meta_livraison_code
            FROM orders
            WHERE id::text = :ref
               OR UPPER(REPLACE(id::text, '-', '')) = UPPER(REPLACE(:ref, '-', ''))
               OR (
                 UPPER(:ref) ~ '^CFG-[0-9A-F]{6,}$'
                 AND UPPER(LEFT(REPLACE(id::text, '-', ''), LENGTH(:ref) - 4)) = UPPER(SUBSTRING(:ref FROM 5))
               )
            LIMIT 2
            """
        ),
        {"ref": external},
    ).mappings().all()
    if len(rows) != 1:
        return None
    row = rows[0]
    stored = str(row.get("meta_livraison_code") or "").strip()
    carrier = str(row.get("carrier") or "")
    if stored and tracking and stored != tracking and carrier and carrier != CARRIER:
        return None
    return row


def apply_webhook(session: Session, raw_body: bytes, signature: str, timestamp: str, event_id: str) -> dict[str, Any]:
    if not verify_signature(raw_body, signature, timestamp, webhook_secret()):
        raise HTTPException(status_code=401, detail="invalid_signature")
    try:
        payload = json.loads(raw_body.decode() or "{}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(payload, dict):
        payload = {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload.get("order") if isinstance(payload.get("order"), dict) else payload
    if not isinstance(data, dict):
        data = {}
    event = str(payload.get("event") or payload.get("type") or payload.get("action") or "")
    external = str(data.get("external_ref") or data.get("externalRef") or data.get("reference") or payload.get("external_ref") or "").strip().lstrip("#")
    tracking = str(data.get("tracking_code") or data.get("trackingCode") or data.get("tracking") or payload.get("tracking_code") or "").strip()
    status_raw = str(data.get("status") or data.get("order_status") or data.get("new_status") or payload.get("status") or "").strip()
    proof = payload.get("proof") if isinstance(payload.get("proof"), dict) else data.get("proof") or data.get("call_proof") or data
    event_key = str(event_id or payload.get("id") or payload.get("event_id") or "")[:120]
    if event_key:
        inserted = session.execute(
            text("INSERT INTO gooli_webhook_events (event_id) VALUES (:id) ON CONFLICT DO NOTHING RETURNING event_id"),
            {"id": event_key},
        ).first()
        if not inserted:
            session.commit()
            return {"ok": True, "duplicate": True}
    order = _find_order(session, external, tracking)
    if not order:
        session.commit()
        return {"ok": True, "matched": False}
    is_proof = "call_proof" in event.lower()
    current = _display_status(str(order.get("status") or ""))
    nxt = None if is_proof else map_status(status_raw)
    if current == "delivered" and nxt in ("shipped", "confirmed"):
        nxt = None
    if current in ("returned", "cancelled") and nxt not in ("delivered", "returned", "cancelled", None):
        nxt = None
    proof_text = json.dumps(proof, ensure_ascii=False)[:4000] if is_proof else ""
    session.execute(
        text(
            """
            UPDATE orders SET
              status = COALESCE(:status, status),
              carrier = CASE
                WHEN :tracking <> '' AND (carrier IS NULL OR BTRIM(carrier) = '' OR carrier = 'gooli' OR COALESCE(BTRIM(meta_livraison_code), '') = '') THEN 'gooli'
                ELSE carrier
              END,
              carrier_status = COALESCE(NULLIF(:carrier_status, ''), carrier_status),
              meta_livraison_code = CASE WHEN :tracking <> '' THEN LEFT(:tracking, 80) ELSE meta_livraison_code END,
              confirmed_at = CASE
                WHEN COALESCE(:status, status) IN ('confirmed','shipped','out_of_zone','delivered','returned') THEN COALESCE(confirmed_at, now())
                ELSE confirmed_at
              END,
              shipped_at = CASE
                WHEN COALESCE(:status, status) IN ('shipped','out_of_zone','delivered','returned') THEN COALESCE(shipped_at, now())
                ELSE shipped_at
              END,
              delivered_at = CASE
                WHEN COALESCE(:status, status) = 'delivered' THEN COALESCE(delivered_at, now())
                WHEN COALESCE(:status, status) IN ('returned','cancelled','shipped','out_of_zone') THEN NULL
                ELSE delivered_at
              END,
              cancelled_at = CASE WHEN COALESCE(:status, status) = 'cancelled' THEN COALESCE(cancelled_at, now()) ELSE NULL END,
              updated_at = now()
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {
            "id": order["id"],
            "status": nxt,
            "tracking": tracking,
            "carrier_status": status_raw[:50],
        },
    )
    if proof_text:
        try:
            session.execute(text("SAVEPOINT gooli_proof"))
            session.execute(
                text("UPDATE orders SET gooli_call_proof = :proof WHERE id = CAST(:id AS uuid)"),
                {"id": order["id"], "proof": proof_text},
            )
            session.execute(text("RELEASE SAVEPOINT gooli_proof"))
        except Exception:
            session.execute(text("ROLLBACK TO SAVEPOINT gooli_proof"))
    try:
        session.execute(text("SAVEPOINT gooli_invoice"))
        session.execute(
            text(
                """
                UPDATE orders
                SET team_payout_paid = CASE WHEN status = 'delivered' THEN team_payout_paid ELSE false END
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": order["id"]},
        )
        session.execute(text("RELEASE SAVEPOINT gooli_invoice"))
    except Exception:
        session.execute(text("ROLLBACK TO SAVEPOINT gooli_invoice"))
    session.commit()
    return {
        "ok": True,
        "matched": True,
        "order_id": order["id"],
        "status": nxt or current,
        "invoice_eligible": nxt == "delivered" and current != "delivered",
    }
