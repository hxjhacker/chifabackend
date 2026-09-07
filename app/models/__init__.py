from sqlmodel import Field, Relationship, SQLModel
import uuid
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(SQLModel, table=True):
    __tablename__ = "products"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(unique=True, index=True, max_length=64)
    name_ar: str = Field(max_length=160)
    name_en: str = Field(max_length=160)
    tagline_ar: str = Field(max_length=240, default="")
    description_ar: str = Field(default="")
    accent: str = Field(max_length=32, default="gold")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)


class Order(SQLModel, table=True):
    __tablename__ = "orders"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    full_name: str = Field(max_length=120)
    phone: str = Field(max_length=20, index=True)
    phone_national: str = Field(max_length=20, default="")
    city: str = Field(max_length=80)
    shipping_city: str | None = Field(default=None, max_length=160)
    address: str | None = Field(default=None)
    quartier: str | None = Field(default=None, max_length=120)
    street: str | None = Field(default=None, max_length=160)
    building: str | None = Field(default=None, max_length=80)
    landmark: str | None = Field(default=None, max_length=160)
    delivery_window: str | None = Field(default=None, max_length=32)
    courier_notes: str | None = Field(default=None)
    region_id: str | None = Field(default=None, max_length=32)
    bundle_enabled: bool = False
    secondary_qty: int = 1
    product_slug: str = Field(max_length=64)
    tier_qty: int
    tier_price_cents: int
    cross_sell_slug: str | None = Field(default=None, max_length=64)
    cross_sell_price_cents: int = 0
    upsell_slug: str | None = Field(default=None, max_length=64)
    upsell_price_cents: int = 0
    subtotal_cents: int
    total_cents: int
    currency: str = Field(default="MAD", max_length=8)
    status: str = Field(default="pending", max_length=32, index=True)
    payment_method: str = Field(default="COD", max_length=16)
    event_id: str = Field(unique=True, index=True, max_length=80)
    fbp: str | None = Field(default=None, max_length=255)
    fbc: str | None = Field(default=None, max_length=512)
    ttclid: str | None = Field(default=None, max_length=512)
    sccid: str | None = Field(default=None, max_length=512)
    client_ip: str | None = Field(default=None, max_length=64)
    user_agent: str | None = Field(default=None)
    landing_url: str | None = Field(default=None)
    source: str = Field(default="website", max_length=32)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    confirmed_at: datetime | None = Field(default=None)
    shipped_at: datetime | None = Field(default=None)
    delivered_at: datetime | None = Field(default=None)
    cancelled_at: datetime | None = Field(default=None)
    meta_livraison_code: str | None = Field(default=None, max_length=80)
    meta_livraison_sent_at: datetime | None = Field(default=None)
    meta_livraison_ticket_url: str | None = Field(default=None)

    items: list["OrderItem"] = Relationship(back_populates="order")


class CityTarif(SQLModel, table=True):
    __tablename__ = "city_tarifs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    meta_city_id: str = Field(index=True, unique=True, max_length=32)
    city_name: str = Field(index=True, max_length=160)
    delivery_fee: float = 35.0
    refusal_fee: float = 10.0
    return_fee: float = 0.0
    hub_name: str | None = Field(default=None, max_length=120)
    updated_at: datetime = Field(default_factory=utcnow)


class OrderItem(SQLModel, table=True):
    __tablename__ = "order_items"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_id: uuid.UUID = Field(foreign_key="orders.id", index=True)
    product_slug: str = Field(max_length=64)
    role: str = Field(max_length=32)
    quantity: int
    unit_price_cents: int
    line_total_cents: int

    order: Order | None = Relationship(back_populates="items")


class TrackingEvent(SQLModel, table=True):
    __tablename__ = "tracking_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    event_id: str = Field(index=True, max_length=80)
    event_name: str = Field(max_length=64)
    platform: str = Field(max_length=32)
    status: str = Field(max_length=32, default="pending")
    detail: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow)


class PageView(SQLModel, table=True):
    __tablename__ = "page_views"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    kind: str = Field(max_length=32)
    product_slug: str | None = Field(default=None, max_length=32, index=True)
    path: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow, index=True)


TrackingEvent = TrackingEvent
PageView = PageView


class PushSubscription(SQLModel, table=True):
    __tablename__ = "push_subscriptions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    endpoint: str = Field(unique=True)
    p256dh: str
    auth: str
    user_agent: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
