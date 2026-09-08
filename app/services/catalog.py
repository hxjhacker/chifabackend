from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy import or_
from sqlmodel import Session, select

from app.models import Product

_CODE_RE = re.compile(r"[^A-Z0-9_-]+")


def clean_product_code(raw: str) -> str:
    text = _CODE_RE.sub("-", str(raw or "").strip().upper())
    text = re.sub(r"[-_]{2,}", "-", text).strip("-_")
    return text[:64]


def auto_product_code(name: str) -> str:
    latin = re.sub(r"[^A-Za-z0-9]+", "_", str(name or "")).strip("_").upper()
    if len(latin) >= 3:
        return latin[:24]
    return f"PRD-{uuid4().hex[:5].upper()}"


def unique_code(session: Session, code: str, exclude_id=None) -> str:
    base = clean_product_code(code) or auto_product_code("")
    candidate = base
    n = 2
    while True:
        q = select(Product).where(Product.code == candidate)
        hit = session.exec(q).first()
        if not hit or (exclude_id is not None and str(hit.id) == str(exclude_id)):
            return candidate
        suffix = f"-{n}"
        candidate = f"{base[: 64 - len(suffix)]}{suffix}"
        n += 1


def unique_slug(session: Session, code: str, exclude_id=None) -> str:
    base = clean_product_code(code).lower().replace("-", "_") or f"prd_{uuid4().hex[:6]}"
    candidate = base[:64]
    n = 2
    while True:
        q = select(Product).where(Product.slug == candidate)
        hit = session.exec(q).first()
        if not hit or (exclude_id is not None and str(hit.id) == str(exclude_id)):
            return candidate
        suffix = f"_{n}"
        candidate = f"{base[: 64 - len(suffix)]}{suffix}"
        n += 1


def dump_product(product: Product) -> dict:
    cents = int(getattr(product, "default_price_cents", 0) or 0)
    return {
        "id": str(product.id),
        "name": product.name_ar,
        "name_ar": product.name_ar,
        "name_en": product.name_en,
        "code": getattr(product, "code", None) or str(product.slug or "").upper(),
        "slug": product.slug,
        "default_price": round(cents / 100, 2),
        "default_price_cents": cents,
        "is_active": bool(product.is_active),
        "created_at": product.created_at.isoformat() if product.created_at else None,
    }


def find_product(session: Session, raw: str) -> Product | None:
    token = str(raw or "").strip()
    if not token:
        return None
    code = clean_product_code(token)
    return session.exec(
        select(Product).where(
            or_(
                Product.slug == token,
                Product.slug == token.lower(),
                Product.code == code,
                Product.code == token.upper(),
            )
        )
    ).first()


def resolve_order_slug(session: Session, raw: str) -> str:
    hit = find_product(session, raw)
    if hit:
        return hit.slug
    code = clean_product_code(raw)
    return code or "quran"


def product_label(session: Session, slug: str) -> str:
    hit = find_product(session, slug)
    if hit:
        return hit.name_ar or hit.code or hit.slug
    return slug
