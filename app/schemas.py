from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    full_name: str = Field(min_length=3, max_length=80)
    phone: str = Field(min_length=9, max_length=20)
    city: str = Field(min_length=2, max_length=80)
    product_slug: str
    tier_qty: int = Field(ge=1, le=3)
    cross_sell_slug: str | None = None
    event_id: str = Field(min_length=8, max_length=80)
    fbp: str | None = None
    fbc: str | None = None
    ttclid: str | None = None
    sccid: str | None = None
    landing_url: str | None = None


class UpsellCreate(BaseModel):
    product_slug: str
    event_id: str = Field(min_length=8, max_length=80)


class TrackingIn(BaseModel):
    event_name: str
    event_id: str
    event_source_url: str | None = None
    value: float | None = None
    currency: str = "MAD"
    content_ids: list[str] = []
    phone: str | None = None
    city: str | None = None
    email: str | None = None
    full_name: str | None = None
    fbp: str | None = None
    fbc: str | None = None
    ttclid: str | None = None
    sccid: str | None = None


OrderCreate = OrderCreate
UpsellCreate = UpsellCreate
TrackingIn = TrackingIn
