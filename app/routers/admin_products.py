from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlmodel import Session, select

from app.db import get_session
from app.dependencies import get_current_admin
from app.models import Product
from app.services.catalog import (
    PROTECTED_SLUGS,
    auto_product_code,
    clean_product_code,
    dump_product,
    parse_quick_product_id,
    unique_code,
    unique_slug,
)

router = APIRouter(prefix="/api/admin", tags=["admin-products"])


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    code: str = ""
    default_price: float | None = 0
    quick_product_id: int | str | None = None
    category: str | None = None
    is_quick_stock: bool | None = None
    stock_quantity: int | None = None
    is_active: bool | None = True


class ProductPatch(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    code: str | None = None
    default_price: float | None = None
    quick_product_id: int | str | None = None
    category: str | None = None
    is_quick_stock: bool | None = None
    stock_quantity: int | None = None
    is_active: bool | None = None


def _quick_id(value: int | str | None) -> int | None:
    try:
        return parse_quick_product_id(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _price_cents(value: float | None) -> int:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if amount < 0:
        raise HTTPException(status_code=422, detail="invalid_price")
    return int(round(amount * 100))


def _stock_qty(value: int | None) -> int:
    try:
        qty = int(value or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="invalid_stock") from None
    if qty < 0:
        raise HTTPException(status_code=422, detail="invalid_stock")
    return qty


def _category(raw: str | None, is_quick: bool) -> str:
    token = str(raw or "").strip().lower()
    if token in {"standard", "quick_stock"}:
        return token
    return "quick_stock" if is_quick else "standard"


def _load(session: Session, product_id: str) -> Product:
    try:
        uid = UUID(product_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="product_not_found") from exc
    product = session.get(Product, uid)
    if not product:
        raise HTTPException(status_code=404, detail="product_not_found")
    return product


@router.get("/products")
def admin_list_products(admin: dict = Depends(get_current_admin), session: Session = Depends(get_session)):
    _ = admin
    rows = session.exec(select(Product).order_by(desc(Product.is_active), Product.category, desc(Product.created_at))).all()
    return {"products": [dump_product(row) for row in rows]}


@router.post("/products", status_code=201)
def admin_create_product(
    payload: ProductIn,
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="invalid_name")
    wanted = clean_product_code(payload.code) or auto_product_code(name)
    code = unique_code(session, wanted)
    slug = unique_slug(session, code)
    quick_id = _quick_id(payload.quick_product_id)
    is_quick = bool(payload.is_quick_stock) if payload.is_quick_stock is not None else bool(quick_id)
    product = Product(
        slug=slug,
        code=code,
        name_ar=name,
        name_en=name,
        default_price_cents=_price_cents(payload.default_price),
        quick_product_id=quick_id,
        category=_category(payload.category, is_quick),
        is_quick_stock=is_quick,
        stock_quantity=_stock_qty(payload.stock_quantity if payload.stock_quantity is not None else (0 if is_quick else 999)),
        is_active=True if payload.is_active is None else bool(payload.is_active),
        accent="gold",
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return dump_product(product)


@router.patch("/products/{product_id}")
def admin_patch_product(
    product_id: str,
    payload: ProductPatch,
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    product = _load(session, product_id)
    if payload.name is not None:
        name = payload.name.strip()
        if len(name) < 2:
            raise HTTPException(status_code=422, detail="invalid_name")
        product.name_ar = name
        if not product.name_en or product.name_en == product.name_ar:
            product.name_en = name
    if payload.code is not None:
        wanted = clean_product_code(payload.code) or auto_product_code(product.name_ar)
        product.code = unique_code(session, wanted, exclude_id=product.id)
        if product.slug not in PROTECTED_SLUGS:
            product.slug = unique_slug(session, product.code, exclude_id=product.id)
    if payload.default_price is not None:
        product.default_price_cents = _price_cents(payload.default_price)
    if "quick_product_id" in payload.model_fields_set:
        product.quick_product_id = _quick_id(payload.quick_product_id)
    if payload.is_quick_stock is not None:
        product.is_quick_stock = bool(payload.is_quick_stock)
    elif "quick_product_id" in payload.model_fields_set:
        product.is_quick_stock = bool(product.quick_product_id)
    if payload.category is not None or payload.is_quick_stock is not None or "quick_product_id" in payload.model_fields_set:
        product.category = _category(payload.category, bool(product.is_quick_stock))
    if payload.stock_quantity is not None:
        product.stock_quantity = _stock_qty(payload.stock_quantity)
    if payload.is_active is not None:
        product.is_active = bool(payload.is_active)
    session.add(product)
    session.commit()
    session.refresh(product)
    return dump_product(product)


@router.delete("/products/{product_id}")
def admin_delete_product(
    product_id: str,
    admin: dict = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    _ = admin
    product = _load(session, product_id)
    product.is_active = False
    session.add(product)
    session.commit()
    return {"ok": True, "id": str(product.id), "is_active": False}
