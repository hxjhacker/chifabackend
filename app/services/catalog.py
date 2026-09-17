from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy import or_
from sqlmodel import Session, select

from app.models import Product

_CODE_RE = re.compile(r"[^A-Z0-9_-]+")
_QUICK_REF_RE = re.compile(r"[^A-Za-z0-9_/-]+")
PROTECTED_SLUGS = {
    "quran",
    "taalim",
    "music",
    "zit_alfasokh",
    "alkhatm_alrijali",
    "almisk_alabyad",
    "pack-royal-power",
}


def clean_product_code(raw: str) -> str:
    original = str(raw or "").strip()
    if "/" in original:
        text = _QUICK_REF_RE.sub("", original)
        text = re.sub(r"/{2,}", "/", text).strip("/")
        return text[:64]
    text = _CODE_RE.sub("-", original.upper())
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
    base = clean_product_code(code).lower().replace("-", "_").replace("/", "_") or f"prd_{uuid4().hex[:6]}"
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
    quick_id = getattr(product, "quick_product_id", None)
    try:
        quick_id = int(quick_id) if quick_id not in (None, "") else None
    except (TypeError, ValueError):
        quick_id = None
    if quick_id is not None and quick_id < 1:
        quick_id = None
    return {
        "id": str(product.id),
        "name": product.name_ar,
        "name_ar": product.name_ar,
        "name_en": product.name_en,
        "code": getattr(product, "code", None) or str(product.slug or "").upper(),
        "slug": product.slug,
        "default_price": round(cents / 100, 2),
        "default_price_cents": cents,
        "quick_product_id": quick_id,
        "category": getattr(product, "category", None) or ("quick_stock" if getattr(product, "is_quick_stock", False) else "standard"),
        "is_quick_stock": bool(getattr(product, "is_quick_stock", False)),
        "stock_quantity": int(getattr(product, "stock_quantity", 0) or 0),
        "is_active": bool(product.is_active),
        "created_at": product.created_at.isoformat() if product.created_at else None,
    }


def find_product(session: Session, raw: str) -> Product | None:
    token = str(raw or "").strip()
    if not token:
        return None
    code = clean_product_code(token)
    clauses = [
        Product.slug == token,
        Product.slug == token.lower(),
        Product.code == token,
        Product.code == token.upper(),
    ]
    if code:
        clauses.extend([Product.code == code, Product.code == code.upper(), Product.slug == code.lower().replace("/", "_")])
    return session.exec(select(Product).where(or_(*clauses))).first()


def resolve_order_slug(session: Session, raw: str) -> str:
    hit = find_product(session, raw)
    if hit:
        return hit.slug
    code = clean_product_code(raw)
    return code.lower().replace("/", "_") or "quran"


def parse_quick_product_id(raw: object) -> int | None:
    if raw in (None, ""):
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError("invalid_quick_product_id") from None
    if value < 1:
        raise ValueError("invalid_quick_product_id")
    return value


def product_label(session: Session, slug: str) -> str:
    hit = find_product(session, slug)
    if hit:
        return hit.name_ar or hit.code or hit.slug
    return slug
