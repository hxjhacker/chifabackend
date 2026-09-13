TIER_PRICE_CENTS = {1: 19900, 2: 27900, 3: 34900}
EDUCATIVE_TIER_PRICE_CENTS = {1: 14900, 2: 24900, 3: 32900}
CROSS_SELL_CENTS = 19900
UPSELL_CENTS = 9900
CURRENCY = "MAD"
CORE_PRODUCT_SLUGS = ("quran", "taalim", "music")
QUICK_STOCK_SLUGS = ("zit_alfasokh", "alkhatm_alrijali", "almisk_alabyad")
LEGACY_PRODUCT_SLUGS = {"kids": "taalim", "educative": "taalim"}
PRODUCT_SLUGS = (*CORE_PRODUCT_SLUGS, *QUICK_STOCK_SLUGS, *LEGACY_PRODUCT_SLUGS)


def canonical_product_slug(slug: str) -> str:
    token = str(slug or "").strip()
    return LEGACY_PRODUCT_SLUGS.get(token, token)


def cents_to_mad(cents: int) -> float:
    return round(cents / 100, 2)


def tier_prices_for(product_slug: str) -> dict[int, int]:
    if product_slug in LEGACY_PRODUCT_SLUGS:
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
    bought = {canonical_product_slug(product_slug or ""), canonical_product_slug(cross_sell_slug or "")}
    return [slug for slug in CORE_PRODUCT_SLUGS if slug not in bought]
