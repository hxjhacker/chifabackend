from __future__ import annotations

import re
import unicodedata

REGION_IDS = tuple(f"MA{i:02d}" for i in range(1, 13))

_HUB_TO_REGION = {
    "fes": "MA03",
    "meknes": "MA03",
    "sefrou": "MA03",
    "taounate": "MA03",
    "taza": "MA03",
    "beni mellal": "MA05",
    "beni-mellal": "MA05",
    "khenifra": "MA05",
    "casa": "MA06",
    "had soualem": "MA06",
    "nador": "MA02",
    "chefchaouen": "MA01",
    "ouazzane": "MA01",
    "agadir": "MA09",
    "tiznit": "MA09",
    "marrakech": "MA07",
    "errachidia": "MA08",
    "tinghir": "MA08",
}

_REGION_KEYWORDS = (
    ("imouzzer kandar", "MA03"),
    ("ait melloul", "MA09"),
    ("el kelaa", "MA07"),
    ("had soualem", "MA06"),
    ("sidi kacem", "MA04"),
    ("sidi slimane", "MA04"),
    ("sidi ifni", "MA10"),
    ("fquih ben salah", "MA05"),
    ("al hoceima", "MA01"),
    ("casablanca", "MA06"),
    ("mohammedia", "MA06"),
    ("benslimane", "MA06"),
    ("berrechid", "MA06"),
    ("berrchid", "MA06"),
    ("bouskoura", "MA06"),
    ("mediouna", "MA06"),
    ("el jadida", "MA06"),
    ("settat", "MA06"),
    ("soualem", "MA06"),
    ("marrakech", "MA07"),
    ("chichaoua", "MA07"),
    ("essaouira", "MA07"),
    ("youssoufia", "MA07"),
    ("rehamna", "MA07"),
    ("beni mellal", "MA05"),
    ("khouribga", "MA05"),
    ("khenifra", "MA05"),
    ("ouaouizeght", "MA05"),
    ("azilal", "MA05"),
    ("inezgane", "MA09"),
    ("taroudant", "MA09"),
    ("chtouka", "MA09"),
    ("errachidia", "MA08"),
    ("ouarzazate", "MA08"),
    ("tinghir", "MA08"),
    ("zagora", "MA08"),
    ("midelt", "MA08"),
    ("chefchaouen", "MA01"),
    ("tetouan", "MA01"),
    ("tanger", "MA01"),
    ("fnideq", "MA01"),
    ("larache", "MA01"),
    ("asilah", "MA01"),
    ("hoceima", "MA01"),
    ("mdiq", "MA01"),
    ("oujda", "MA02"),
    ("berkane", "MA02"),
    ("driouch", "MA02"),
    ("jerada", "MA02"),
    ("taourirt", "MA02"),
    ("guercif", "MA02"),
    ("figuig", "MA02"),
    ("nador", "MA02"),
    ("meknes", "MA03"),
    ("sefrou", "MA03"),
    ("ifrane", "MA03"),
    ("azrou", "MA03"),
    ("taounate", "MA03"),
    ("bhalil", "MA03"),
    ("imouzzer", "MA03"),
    ("temara", "MA04"),
    ("kenitra", "MA04"),
    ("skhirat", "MA04"),
    ("khemisset", "MA04"),
    ("rabat", "MA04"),
    ("guelmim", "MA10"),
    ("tantan", "MA10"),
    ("tan tan", "MA10"),
    ("boujdour", "MA11"),
    ("tarfaya", "MA11"),
    ("laayoune", "MA11"),
    ("smara", "MA11"),
    ("essmara", "MA11"),
    ("dakhla", "MA12"),
    ("aousserd", "MA12"),
    ("agadir", "MA09"),
    ("tiznit", "MA09"),
    ("tata", "MA09"),
    ("safi", "MA07"),
    ("taza", "MA03"),
    ("fes", "MA03"),
    ("sale", "MA04"),
    ("casa", "MA06"),
)


def _fold(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("-", " ")
    return re.sub(r"\s+", " ", value).strip()


def region_id_for_city(city: str) -> str:
    raw = (city or "").strip()
    if not raw:
        return "MA06"
    if " - " in raw:
        hub = _fold(raw.rsplit(" - ", 1)[-1])
        if hub in _HUB_TO_REGION:
            return _HUB_TO_REGION[hub]
    folded = _fold(raw)
    for keyword, region_id in _REGION_KEYWORDS:
        if keyword in folded or (len(keyword) >= 5 and folded in keyword):
            return region_id
    return "MA06"
