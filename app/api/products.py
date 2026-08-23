from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Product

router = APIRouter(prefix="/api")


def _dump(product: Product) -> dict:
    return {
        "slug": product.slug,
        "name_ar": product.name_ar,
        "name_en": product.name_en,
        "tagline_ar": product.tagline_ar,
        "description_ar": product.description_ar,
        "accent": product.accent,
    }


@router.get("/products")
def list_products(session: Session = Depends(get_session)):
    rows = session.exec(select(Product).where(Product.is_active == True)).all()  # noqa: E712
    return {"products": [_dump(p) for p in rows]}


@router.get("/products/{slug}")
def get_product(slug: str, session: Session = Depends(get_session)):
    product = session.exec(select(Product).where(Product.slug == slug)).first()
    if not product or not product.is_active:
        raise HTTPException(status_code=404, detail="product_not_found")
    return _dump(product)
