import re

_PHONE_RE = re.compile(r"^\+212[567]\d{8}$")


def digits_only(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def normalize_ma_phone(raw: str) -> str:
    """Return E.164 (+212[5-7]xxxxxxxx) or raise ValueError."""
    digits = digits_only(raw)
    if digits.startswith("00212"):
        digits = digits[2:]
    if digits.startswith("212") and len(digits) == 12 and digits[3] in "567":
        e164 = "+" + digits
    elif len(digits) == 10 and digits[0] == "0" and digits[1] in "567":
        e164 = "+212" + digits[1:]
    elif len(digits) == 9 and digits[0] in "567":
        e164 = "+212" + digits
    else:
        raise ValueError("invalid_ma_phone")
    if not _PHONE_RE.match(e164):
        raise ValueError("invalid_ma_phone")
    return e164


def to_national(e164: str) -> str:
    if e164.startswith("+212") and len(e164) == 13:
        return "0" + e164[4:]
    return e164


def phone_digits_for_hash(e164: str) -> str:
    """Meta/TikTok/Snap: country code + number, no plus, no leading zero."""
    return digits_only(e164)


normalize_ma_phone = normalize_ma_phone
to_national = to_national
phone_digits_for_hash = phone_digits_for_hash
