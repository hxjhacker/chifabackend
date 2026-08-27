TIER_PRICE_CENTS = {1: 19900, 2: 27900, 3: 34900}
EDUCATIVE_TIER_PRICE_CENTS = {1: 14900, 2: 24900, 3: 32900}
CROSS_SELL_CENTS = 19900
UPSELL_CENTS = 9900
CURRENCY = "MAD"
CORE_PRODUCT_SLUGS = ("quran", "kids", "music")
PRODUCT_SLUGS = (*CORE_PRODUCT_SLUGS, "educative")


def cents_to_mad(cents: int) -> float:
    return round(cents / 100, 2)


def tier_prices_for(product_slug: str) -> dict[int, int]:
    if product_slug == "educative":
        return EDUCATIVE_TIER_PRICE_CENTS
    return TIER_PRICE_CENTS


def compute_subtotal(
    tier_qty: int,
    has_cross_sell: bool,
    product_slug: str = "quran",
) -> tuple[int, int, int]:
    table = tier_prices_for(product_slug)
    if tier_qty not in table:
        raise ValueError("invalid_tier")
    tier = table[tier_qty]
    cross = CROSS_SELL_CENTS if has_cross_sell else 0
    return tier, cross, tier + cross


def upsell_candidates(product_slug: str | None, cross_sell_slug: str | None) -> list[str]:
    bought = {product_slug, cross_sell_slug}
    if "educative" in bought:
        bought.add("kids")
    return [slug for slug in CORE_PRODUCT_SLUGS if slug not in bought]


TIER_PRICE_CENTS = TIER_PRICE_CENTS
CROSS_SELL_CENTS = CROSS_SELL_CENTS
UPSELL_CENTS = UPSELL_CENTS
PRODUCT_SLUGS = PRODUCT_SLUGS
cents_to_mad = cents_to_mad
compute_subtotal = compute_subtotal
