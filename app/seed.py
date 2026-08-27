from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Session, select

from app.models import Product

CATALOG = [
    {
        "slug": "quran",
        "name_ar": "USB القرآن الكريم",
        "name_en": "Holy Quran USB",
        "tagline_ar": "القرآن كامل بجودة عالية… يتسمع في الدار والسيارة.",
        "description_ar": "مكتبة قرآنية فاخرة على USB جاهز للتشغيل، مناسب للإهداء وللاستماع اليومي بدون نت.",
        "accent": "gold",
    },
    {
        "slug": "kids",
        "name_ar": "USB تعليم الأطفال",
        "name_en": "Children Learning USB",
        "tagline_ar": "محتوى تربوي جاهز… ولادك يتعلمو وأنت مرتاح.",
        "description_ar": "تجميعة تعليمية للأطفال: حروف، أرقام، أناشيد وألعاب تعلم، بلا إعلانات وبلا نت.",
        "accent": "emerald",
    },
    {
        "slug": "music",
        "name_ar": "USB الأغاني والموسيقى",
        "name_en": "Music & Songs USB",
        "tagline_ar": "موسيقى جاهزة، بلا نت وبلا تقطيعة.",
        "description_ar": "مكتبة أغاني مرتبة للسيارة، المحل، والتجمعات العائلية — تشغيل مباشر من الـ USB.",
        "accent": "bronze",
    },
    {
        "slug": "educative",
        "name_ar": "الفلاشة التعليمية الذكية للأطفال",
        "name_en": "Smart Educational USB for Kids",
        "tagline_ar": "100% بدون إنترنت — رفيق التفوق المدرسي وحماية طفلك من إدمان الهواتف.",
        "description_ar": "فلاشة تربوية جاهزة للتلفاز والحاسوب: قرآن، لغات، حساب، وقصص هادفة بلا إعلانات وبلا نت.",
        "accent": "emerald",
    },
]


def seed_products(session: Session) -> None:
    for item in CATALOG:
        existing = session.exec(select(Product).where(Product.slug == item["slug"])).first()
        if existing:
            existing.name_ar = item["name_ar"]
            existing.name_en = item["name_en"]
            existing.tagline_ar = item["tagline_ar"]
            existing.description_ar = item["description_ar"]
            existing.accent = item["accent"]
            existing.is_active = True
            continue
        session.add(
            Product(
                id=uuid4(),
                slug=item["slug"],
                name_ar=item["name_ar"],
                name_en=item["name_en"],
                tagline_ar=item["tagline_ar"],
                description_ar=item["description_ar"],
                accent=item["accent"],
                created_at=datetime.now(timezone.utc),
            )
        )
    session.commit()
