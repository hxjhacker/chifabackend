"""Canonical 6-product catalog: 3 local USBs + 3 Quick warehouse SKUs."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import or_
from sqlmodel import Session, select

from app.models import Order, OrderItem, Product

CATALOG = [
    {
        "slug": "quran",
        "code": "USB_QURAN",
        "name_ar": "USB القرآن",
        "name_en": "USB quran",
        "tagline_ar": "مصحف كامل بجودة عالية للدار والسيارة.",
        "description_ar": "USB القرآن الكريم — تنفيذ محلي، ليس من مخزون Quick.",
        "accent": "gold",
        "category": "standard",
        "is_quick_stock": False,
        "quick_product_id": None,
        "stock_quantity": 999,
        "default_price_cents": 19900,
    },
    {
        "slug": "taalim",
        "code": "USB_TAALIMI",
        "name_ar": "USB التعليمي",
        "name_en": "USB taalimi",
        "tagline_ar": "محتوى تربوي جاهز بدون نت.",
        "description_ar": "USB تعليمي — تنفيذ محلي، ليس من مخزون Quick.",
        "accent": "emerald",
        "category": "standard",
        "is_quick_stock": False,
        "quick_product_id": None,
        "stock_quantity": 999,
        "default_price_cents": 19900,
    },
    {
        "slug": "music",
        "code": "USB_MOSIQII",
        "name_ar": "USB الموسيقى",
        "name_en": "USB mosi9ii",
        "tagline_ar": "موسيقى جاهزة بلا نت وبلا تقطيعة.",
        "description_ar": "USB موسيقى — تنفيذ محلي، ليس من مخزون Quick.",
        "accent": "bronze",
        "category": "standard",
        "is_quick_stock": False,
        "quick_product_id": None,
        "stock_quantity": 999,
        "default_price_cents": 19900,
    },
    {
        "slug": "zit_alfasokh",
        "code": "zital2/7513",
        "name_ar": "زيت الفسوخ",
        "name_en": "zit alfasokh",
        "tagline_ar": "مخزون Quick Livraison — خصم تلقائي.",
        "description_ar": "زيت الفسوخ من مخزون Quick. المرجع zital2/7513.",
        "accent": "gold",
        "category": "quick_stock",
        "is_quick_stock": True,
        "quick_product_id": 5775,
        "stock_quantity": 2,
        "default_price_cents": 24900,
    },
    {
        "slug": "alkhatm_alrijali",
        "code": "KH01/7513",
        "name_ar": "الخاتم الرجالي",
        "name_en": "alkhatm alrijali",
        "tagline_ar": "مخزون Quick Livraison — خصم تلقائي.",
        "description_ar": "الخاتم الرجالي من مخزون Quick. المرجع KH01/7513.",
        "accent": "gold",
        "category": "quick_stock",
        "is_quick_stock": True,
        "quick_product_id": 6005,
        "stock_quantity": 79,
        "default_price_cents": 29900,
    },
    {
        "slug": "almisk_alabyad",
        "code": "MSK_01/7513",
        "name_ar": "المسك الأبيض",
        "name_en": "almisk alabyad",
        "tagline_ar": "مخزون Quick Livraison — خصم تلقائي.",
        "description_ar": "المسك الأبيض من مخزون Quick. المرجع MSK_01/7513.",
        "accent": "gold",
        "category": "quick_stock",
        "is_quick_stock": True,
        "quick_product_id": 6107,
        "stock_quantity": 22,
        "default_price_cents": 19900,
    },
    {
        "slug": "pack-royal-power",
        "code": "PACK_ROYAL",
        "name_ar": "الباك الملكي",
        "name_en": "Royal Power Pack",
        "tagline_ar": "الزيت الملكي + العسل الملكي بالأعشاب — طاقة وصلابة طبيعية.",
        "description_ar": "باك رجالي: زيت ملكي للتدليك الخارجي وعسل ملكي بالأعشاب للاستعمال اليومي. تغليف سري والدفع عند الاستلام.",
        "accent": "emerald",
        "category": "standard",
        "is_quick_stock": False,
        "quick_product_id": None,
        "stock_quantity": 999,
        "default_price_cents": 29900,
    },
]

KEEP_SLUGS = {item["slug"] for item in CATALOG}
KEEP_CODES = {item["code"] for item in CATALOG}


def _apply(product: Product, item: dict, *, reset_stock: bool, is_new: bool) -> None:
    product.slug = item["slug"]
    product.code = item["code"]
    product.name_ar = item["name_ar"]
    product.name_en = item["name_en"]
    product.tagline_ar = item["tagline_ar"]
    product.description_ar = item["description_ar"]
    product.accent = item["accent"]
    product.category = item["category"]
    product.quick_product_id = item["quick_product_id"]
    product.default_price_cents = int(item["default_price_cents"])
    product.is_active = True
    becoming_quick = bool(item["is_quick_stock"]) and not bool(getattr(product, "is_quick_stock", False))
    if is_new or reset_stock or not item["is_quick_stock"] or becoming_quick:
        product.stock_quantity = int(item["stock_quantity"])
    product.is_quick_stock = bool(item["is_quick_stock"])


def _find_existing(session: Session, item: dict) -> Product | None:
    hit = session.exec(
        select(Product).where(
            or_(
                Product.slug == item["slug"],
                Product.code == item["code"],
                Product.code == str(item["code"]).upper(),
            )
        )
    ).first()
    if hit:
        return hit
    quick_id = item.get("quick_product_id")
    if quick_id:
        return session.exec(select(Product).where(Product.quick_product_id == int(quick_id))).first()
    return None


def _referenced_slugs(session: Session) -> set[str]:
    slugs: set[str] = set()
    try:
        for slug in session.exec(select(Order.product_slug).distinct()).all():
            if slug:
                slugs.add(str(slug))
        for slug in session.exec(select(Order.cross_sell_slug).distinct()).all():
            if slug:
                slugs.add(str(slug))
        for slug in session.exec(select(OrderItem.product_slug).distinct()).all():
            if slug:
                slugs.add(str(slug))
    except Exception:
        pass
    return slugs


def seed_products(session: Session, *, reset_stock: bool = False) -> dict:
    """Upsert the 6 catalog products and deactivate leftovers. Never delete rows still referenced by orders."""
    now = datetime.now(timezone.utc)
    upserted = 0
    created = 0
    for item in CATALOG:
        existing = _find_existing(session, item)
        if existing:
            _apply(existing, item, reset_stock=reset_stock, is_new=False)
            session.add(existing)
            upserted += 1
            continue
        product = Product(
            id=uuid4(),
            created_at=now,
        )
        _apply(product, item, reset_stock=True, is_new=True)
        session.add(product)
        created += 1

    referenced = _referenced_slugs(session)
    deactivated = 0
    kept_history = 0
    leftovers = session.exec(select(Product)).all()
    for product in leftovers:
        if product.slug in KEEP_SLUGS or product.code in KEEP_CODES:
            continue
        if product.slug in referenced:
            product.is_active = False
            session.add(product)
            kept_history += 1
            continue
        session.delete(product)
        deactivated += 1

    session.commit()
    return {
        "created": created,
        "updated": upserted,
        "deactivated": deactivated,
        "kept_for_order_history": kept_history,
        "active_catalog": sorted(KEEP_SLUGS),
    }
