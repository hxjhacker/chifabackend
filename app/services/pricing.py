TIER_PRICE_CENTS = {1: 19900, 2: 27900, 3: 34900}
CROSS_SELL_CENTS = 19900
UPSELL_CENTS = 9900
CURRENCY = "MAD"
PRODUCT_SLUGS = ("quran", "kids", "music")


def cents_to_mad(cents: int) -> float:
    return round(cents / 100, 2)


def compute_subtotal(tier_qty: int, has_cross_sell: bool) -> tuple[int, int, int]:
    if tier_qty not in TIER_PRICE_CENTS:
        raise ValueError("invalid_tier")
    tier = TIER_PRICE_CENTS[tier_qty]
    cross = CROSS_SELL_CENTS if has_cross_sell else 0
    return tier, cross, tier + cross


TIER_PRICE_CENTS = TIER_PRICE_CENTS
CROSS_SELL_CENTS = CROSS_SELL_CENTS
UPSELL_CENTS = UPSELL_CENTS
PRODUCT_SLUGS = PRODUCT_SLUGS
cents_to_mad = cents_to_mad
compute_subtotal = compute_subtotal
