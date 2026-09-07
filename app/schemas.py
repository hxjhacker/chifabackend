from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrderCreate(BaseModel):
    full_name: str = Field(min_length=3, max_length=80)
    phone: str = Field(min_length=9, max_length=20)
    city: str = Field(min_length=2, max_length=80)
    address: str | None = Field(default=None, max_length=2000)
    product_slug: str
    tier_qty: int = Field(ge=1, le=3)
    cross_sell_slug: str | None = None
    event_id: str = Field(min_length=8, max_length=80)
    fbp: str | None = None
    fbc: str | None = None
    ttclid: str | None = None
    sccid: str | None = None
    landing_url: str | None = None
    defer_purchase: bool = False


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


class OrderUpdate(BaseModel):
    """Admin confirm/edit payload. Every field is optional so extra/missing keys do not 422."""

    model_config = ConfigDict(extra="ignore")

    customer_name: str | None = None
    full_name: str | None = None
    city: str | None = None
    shipping_city: str | None = None
    region: str | None = None
    region_id: str | None = None
    full_address: str | None = None
    address: str | None = None
    primary_product: str | None = None
    product_slug: str | None = None
    primary_qty: int | None = None
    tier_qty: int | None = None
    bundle_enabled: bool | None = None
    secondary_product: str | None = None
    cross_sell_slug: str | None = None
    secondary_qty: int | None = None
    total_price: float | None = None
    total_mad: float | None = None
    driver_comment: str | None = None
    courier_notes: str | None = None
    status: str | None = None
    phone: str | None = None
    quartier: str | None = None
    street: str | None = None
    building: str | None = None
    landmark: str | None = None
    delivery_window: str | None = None
    cross_sell_price_mad: float | None = None
    carrier: str | None = None

    @model_validator(mode="before")
    @classmethod
    def coerce_aliases(cls, data: object):
        if not isinstance(data, dict):
            return data
        aliases = {
            "full_name": ("full_name", "fullName", "customer_name", "customerName"),
            "customer_name": ("customer_name", "customerName"),
            "shipping_city": ("shipping_city", "shippingCity", "meta_city", "metaCity"),
            "region": ("region", "region_id", "regionId"),
            "region_id": ("region_id", "regionId", "region"),
            "address": ("address", "full_address", "fullAddress"),
            "full_address": ("full_address", "fullAddress"),
            "product_slug": ("product_slug", "productSlug", "primary_product", "primaryProduct"),
            "primary_product": ("primary_product", "primaryProduct"),
            "tier_qty": ("tier_qty", "tierQty", "primary_qty", "primaryQty"),
            "primary_qty": ("primary_qty", "primaryQty"),
            "bundle_enabled": ("bundle_enabled", "bundleEnabled"),
            "cross_sell_slug": ("cross_sell_slug", "crossSellSlug", "secondary_product", "secondaryProduct"),
            "secondary_product": ("secondary_product", "secondaryProduct"),
            "secondary_qty": ("secondary_qty", "secondaryQty"),
            "total_mad": ("total_mad", "totalMad", "total_price", "totalPrice"),
            "total_price": ("total_price", "totalPrice"),
            "courier_notes": ("courier_notes", "courierNotes", "driver_comment", "driverComment"),
            "driver_comment": ("driver_comment", "driverComment"),
            "cross_sell_price_mad": ("cross_sell_price_mad", "crossSellPriceMad"),
        }
        out = dict(data)
        for dest, keys in aliases.items():
            if dest in out and out[dest] is not None:
                continue
            for key in keys:
                if key in data:
                    out[dest] = data[key]
                    break

        def as_num(value: object):
            if value is None or value == "":
                return None
            try:
                return float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        def as_flag(value: object):
            if isinstance(value, bool) or value is None:
                return value
            text = str(value).strip().lower()
            if text in ("true", "1"):
                return True
            if text in ("false", "0"):
                return False
            return value

        for key in ("tier_qty", "primary_qty", "secondary_qty"):
            if key in out and out[key] is not None:
                parsed = as_num(out[key])
                out[key] = int(parsed) if parsed is not None else None
        for key in ("total_mad", "total_price", "cross_sell_price_mad"):
            if key in out and out[key] is not None:
                out[key] = as_num(out[key])
        if "bundle_enabled" in out:
            out["bundle_enabled"] = as_flag(out["bundle_enabled"])
        return out


class AdminOrderPatch(OrderUpdate):
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
