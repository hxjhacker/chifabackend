from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    full_name: str = Field(min_length=3, max_length=80)
    phone: str = Field(min_length=9, max_length=20)
    city: str = Field(min_length=2, max_length=80)
    address: str | None = Field(default=None, max_length=500)
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


class AdminOrderPatch(BaseModel):
    status: str | None = None
    full_name: str | None = Field(default=None, min_length=3, max_length=120)
    phone: str | None = None
    city: str | None = None
    product_slug: str | None = None
    primary_product: str | None = None
    tier_qty: int | None = Field(default=None, ge=1, le=20)
    primary_qty: int | None = Field(default=None, ge=1, le=20)
    total_mad: float | None = Field(default=None, ge=1)
    total_price: float | None = Field(default=None, ge=1)
    quartier: str | None = Field(default=None, max_length=120)
    street: str | None = Field(default=None, max_length=160)
    building: str | None = Field(default=None, max_length=80)
    landmark: str | None = Field(default=None, max_length=160)
    delivery_window: str | None = None
    courier_notes: str | None = None
    driver_comment: str | None = None
    address: str | None = None
    full_address: str | None = None
    region_id: str | None = None
    region: str | None = None
    cross_sell_slug: str | None = None
    secondary_product: str | None = None
    cross_sell_price_mad: float | None = None
    bundle_enabled: bool | None = None
    secondary_qty: int | None = Field(default=None, ge=1, le=20)


class OrderUpdate(AdminOrderPatch):
    pass


class OrderResponse(BaseModel):
    order_id: str
    full_name: str
    city: str
    phone: str
    status: str
    full_address: str | None = None
    region: str | None = None
    primary_product: str | None = None
    primary_qty: int | None = 1
    bundle_enabled: bool | None = False
    secondary_product: str | None = None
    secondary_qty: int | None = 1
    driver_comment: str | None = None
    total_price: float | None = None


OrderCreate = OrderCreate
UpsellCreate = UpsellCreate
TrackingIn = TrackingIn
AdminOrderPatch = AdminOrderPatch
OrderUpdate = OrderUpdate
OrderResponse = OrderResponse

