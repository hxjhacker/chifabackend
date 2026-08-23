import hashlib
import re
import unicodedata


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _collapse(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\u0640", "")
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


def hash_email(email: str | None) -> str | None:
    if not email:
        return None
    return sha256_hex(_collapse(email))


def hash_phone_digits(digits: str) -> str:
    return sha256_hex(digits)


def hash_city(city_latin: str) -> str:
    return sha256_hex(_collapse(city_latin))


def split_name(full_name: str) -> tuple[str, str]:
    parts = _collapse(full_name).split(" ")
    first = parts[0] if parts else ""
    last = " ".join(parts[1:]) if len(parts) > 1 else (parts[0] if parts else "")
    return first, last


def hash_name_parts(full_name: str) -> tuple[str, str]:
    first, last = split_name(full_name)
    return sha256_hex(first), sha256_hex(last)


hash_email = hash_email
sha256_hex = sha256_hex
hash_name_parts = hash_name_parts
hash_phone_digits = hash_phone_digits
hash_email = hash_email
sha256_hex = sha256_hex
hash_name_parts = hash_name_parts
hash_phone_digits = hash_phone_digits
