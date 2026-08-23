from __future__ import annotations

CITIES: list[dict[str, object]] = [
    {"ar": "الدار البيضاء", "fr": "Casablanca", "aliases": ["casa", "casablanca", "الدارالبيضاء"]},
    {"ar": "الرباط", "fr": "Rabat", "aliases": ["rabat"]},
    {"ar": "سلا", "fr": "Sale", "aliases": ["salé", "sale", "sala"]},
    {"ar": "تمارة", "fr": "Temara", "aliases": ["témara", "temara"]},
    {"ar": "القنيطرة", "fr": "Kenitra", "aliases": ["kénitra", "kenitra", "qnitra"]},
    {"ar": "فاس", "fr": "Fes", "aliases": ["fès", "fes", "fez"]},
    {"ar": "مكناس", "fr": "Meknes", "aliases": ["meknès", "meknes"]},
    {"ar": "مراكش", "fr": "Marrakech", "aliases": ["marrakesh", "marrakech"]},
    {"ar": "أكادير", "fr": "Agadir", "aliases": ["agadir"]},
    {"ar": "طنجة", "fr": "Tanger", "aliases": ["tangier", "tanger", "tangiers"]},
    {"ar": "تطوان", "fr": "Tetouan", "aliases": ["tétouan", "tetouan"]},
    {"ar": "وجدة", "fr": "Oujda", "aliases": ["oujda"]},
    {"ar": "الناظور", "fr": "Nador", "aliases": ["nador"]},
    {"ar": "الجديدة", "fr": "El Jadida", "aliases": ["eljadida", "jadida"]},
    {"ar": "آسفي", "fr": "Safi", "aliases": ["safi"]},
    {"ar": "الصويرة", "fr": "Essaouira", "aliases": ["essaouira", "mogador"]},
    {"ar": "المحمدية", "fr": "Mohammedia", "aliases": ["mohammedia", "fedala"]},
    {"ar": "بني ملال", "fr": "Beni Mellal", "aliases": ["beni mellal", "benimellal"]},
    {"ar": "خريبكة", "fr": "Khouribga", "aliases": ["khouribga"]},
    {"ar": "سطات", "fr": "Settat", "aliases": ["settat"]},
    {"ar": "برشيد", "fr": "Berrechid", "aliases": ["berrechid"]},
    {"ar": "تازة", "fr": "Taza", "aliases": ["taza"]},
    {"ar": "العرائش", "fr": "Larache", "aliases": ["larache"]},
    {"ar": "القصر الكبير", "fr": "Ksar El Kebir", "aliases": ["ksar", "el ksar"]},
    {"ar": "الحسيمة", "fr": "Al Hoceima", "aliases": ["alhoceima", "al hoceima", "hoceima"]},
    {"ar": "الرشيدية", "fr": "Errachidia", "aliases": ["errachidia", "rachidia"]},
    {"ar": "ورزازات", "fr": "Ouarzazate", "aliases": ["ouarzazate"]},
    {"ar": "زاكورة", "fr": "Zagora", "aliases": ["zagora"]},
    {"ar": "الداخلة", "fr": "Dakhla", "aliases": ["dakhla"]},
    {"ar": "العيون", "fr": "Laayoune", "aliases": ["laâyoune", "laayoune", "el aaiun"]},
    {"ar": "تارودانت", "fr": "Taroudant", "aliases": ["taroudant", "taroudannt"]},
    {"ar": "إنزكان", "fr": "Inezgane", "aliases": ["inezgane"]},
    {"ar": "أيت ملول", "fr": "Ait Melloul", "aliases": ["ait melloul", "aït melloul"]},
    {"ar": "تيزنيت", "fr": "Tiznit", "aliases": ["tiznit"]},
    {"ar": "كلميم", "fr": "Guelmim", "aliases": ["guelmim", "goulimine"]},
    {"ar": "طانطان", "fr": "Tan Tan", "aliases": ["tantan", "tan-tan"]},
    {"ar": "بركان", "fr": "Berkane", "aliases": ["berkane"]},
    {"ar": "تاوريرت", "fr": "Taourirt", "aliases": ["taourirt"]},
    {"ar": "جرسيف", "fr": "Guercif", "aliases": ["guercif"]},
    {"ar": "سيدي قاسم", "fr": "Sidi Kacem", "aliases": ["sidi kacem"]},
    {"ar": "سيدي سليمان", "fr": "Sidi Slimane", "aliases": ["sidi slimane"]},
    {"ar": "سوق الأربعاء", "fr": "Souk El Arbaa", "aliases": ["souk el arbaa"]},
    {"ar": "وزان", "fr": "Ouazzane", "aliases": ["ouazzane", "wazzan"]},
    {"ar": "شفشاون", "fr": "Chefchaouen", "aliases": ["chefchaouen", "chaouen", "shafshawan"]},
    {"ar": "الفنيدق", "fr": "Fnideq", "aliases": ["fnideq", "fnidek"]},
    {"ar": "المضيق", "fr": "Mdiq", "aliases": ["m'diq", "mdiq", "martil-mdiq"]},
    {"ar": "مرتيل", "fr": "Martil", "aliases": ["martil"]},
    {"ar": "أصيلة", "fr": "Asilah", "aliases": ["asilah", "arcila"]},
    {"ar": "تيفلت", "fr": "Tiflet", "aliases": ["tiflet"]},
    {"ar": "الخميسات", "fr": "Khemisset", "aliases": ["khémisset", "khemisset"]},
    {"ar": "صفرو", "fr": "Sefrou", "aliases": ["sefrou"]},
    {"ar": "إفران", "fr": "Ifrane", "aliases": ["ifrane"]},
    {"ar": "أزرو", "fr": "Azrou", "aliases": ["azrou"]},
    {"ar": "ميدلت", "fr": "Midelt", "aliases": ["midelt"]},
    {"ar": "خنيفرة", "fr": "Khenifra", "aliases": ["khénifra", "khenifra"]},
    {"ar": "الفقيه بن صالح", "fr": "Fquih Ben Salah", "aliases": ["fquih ben salah", "souk sebt"]},
    {"ar": "أزيلال", "fr": "Azilal", "aliases": ["azilal"]},
    {"ar": "قلعة السراغنة", "fr": "El Kelaa des Sraghna", "aliases": ["kelaa", "qal'at"]},
    {"ar": "شيشاوة", "fr": "Chichaoua", "aliases": ["chichaoua"]},
    {"ar": "اليوسفية", "fr": "Youssoufia", "aliases": ["youssoufia"]},
    {"ar": "الصخيرات", "fr": "Skhirat", "aliases": ["skhirat", "skhirate"]},
    {"ar": "بوزنيقة", "fr": "Bouznika", "aliases": ["bouznika"]},
    {"ar": "بنسليمان", "fr": "Benslimane", "aliases": ["benslimane"]},
    {"ar": "وادي زم", "fr": "Oued Zem", "aliases": ["oued zem"]},
    {"ar": "قصبة تادلة", "fr": "Kasba Tadla", "aliases": ["kasba tadla"]},
    {"ar": "الراشدية", "fr": "Errachidia Centre", "aliases": []},
    {"ar": "تنغير", "fr": "Tinghir", "aliases": ["tinghir", "tinerhir"]},
    {"ar": "الريصاني", "fr": "Rissani", "aliases": ["rissani"]},
    {"ar": "أكدز", "fr": "Agdz", "aliases": ["agdz"]},
    {"ar": "تافراوت", "fr": "Tafraout", "aliases": ["tafraout"]},
    {"ar": "بيوكرى", "fr": "Biougra", "aliases": ["biougra"]},
    {"ar": "ماسة", "fr": "Massa", "aliases": ["massa"]},
    {"ar": "سيدي إفني", "fr": "Sidi Ifni", "aliases": ["sidi ifni"]},
    {"ar": "بوجدور", "fr": "Boujdour", "aliases": ["boujdour", "bojador"]},
    {"ar": "السمارة", "fr": "Smara", "aliases": ["smara", "es semara"]},
    {"ar": "جرادة", "fr": "Jerada", "aliases": ["jerada"]},
    {"ar": "عين عودة", "fr": "Ain Aouda", "aliases": ["ain aouda"]},
    {"ar": "عين حرودة", "fr": "Ain Harrouda", "aliases": ["ain harrouda"]},
    {"ar": "سيدي يحيى الغرب", "fr": "Sidi Yahya El Gharb", "aliases": ["sidi yahya"]},
    {"ar": "سيدي بنور", "fr": "Sidi Bennour", "aliases": ["sidi bennour"]},
    {"ar": "بركان المركز", "fr": "Ahfir", "aliases": ["ahfir"]},
    {"ar": "زايو", "fr": "Zaio", "aliases": ["zaio"]},
    {"ar": "الدريوش", "fr": "Driouch", "aliases": ["driouch"]},
    {"ar": "الحاجب", "fr": "El Hajeb", "aliases": ["el hajeb", "hajeb"]},
    {"ar": "مولاي يعقوب", "fr": "Moulay Yacoub", "aliases": ["moulay yacoub"]},
    {"ar": "تاونات", "fr": "Taounate", "aliases": ["taounate"]},
    {"ar": "وزان الجبل", "fr": "Bab Berred", "aliases": ["bab berred"]},
    {"ar": "كتامة", "fr": "Ketama", "aliases": ["ketama", "issaguen"]},
    {"ar": "شفشاون الجبل", "fr": "Bab Taza", "aliases": ["bab taza"]},
    {"ar": "القصر الصغير", "fr": "Ksar Sghir", "aliases": ["ksar sghir"]},
    {"ar": "الفحص أنجرة", "fr": "Fahs Anjra", "aliases": ["anjra"]},
    {"ar": "سيدي رحال", "fr": "Sidi Rahal", "aliases": ["sidi rahal"]},
    {"ar": "الدروة", "fr": "Dar Bouazza", "aliases": ["dar bouazza"]},
    {"ar": "النواصر", "fr": "Nouaceur", "aliases": ["nouaceur", "nasser"]},
    {"ar": "مديونة", "fr": "Mediouna", "aliases": ["mediouna"]},
    {"ar": "تيط مليل", "fr": "Tit Mellil", "aliases": ["tit mellil"]},
    {"ar": "عين السبع", "fr": "Ain Sebaa", "aliases": ["ain sebaa"]},
    {"ar": "سيدي موسى", "fr": "Sidi Moumen", "aliases": ["sidi moumen"]},
    {"ar": "الحي المحمدي", "fr": "Hay Mohammadi", "aliases": []},
    {"ar": "إنزكان آيت ملول", "fr": "Inezgane Ait Melloul", "aliases": []},
    {"ar": "أولاد تايمة", "fr": "Oulad Teima", "aliases": ["ouled teima"]},
    {"ar": "تارودانت المركز", "fr": "Ouled Berhil", "aliases": ["ouled berhil"]},
    {"ar": "تامنصورت", "fr": "Tamesloht", "aliases": ["tamesloht"]},
    {"ar": "تحناوت", "fr": "Tahannaout", "aliases": ["tahannaout"]},
    {"ar": "أمزميز", "fr": "Amizmiz", "aliases": ["amizmiz"]},
    {"ar": "قلعة مكونة", "fr": "Kalaat M'Gouna", "aliases": ["kalaat mgouna"]},
    {"ar": "بومالن دادس", "fr": "Boumalne Dades", "aliases": ["boumalne"]},
    {"ar": "الريش", "fr": "Rich", "aliases": ["rich"]},
    {"ar": "كلميمة", "fr": "Goulmima", "aliases": ["goulmima"]},
    {"ar": "أرفود", "fr": "Erfoud", "aliases": ["erfoud"]},
    {"ar": "مرزوكة", "fr": "Merzouga", "aliases": ["merzouga"]},
]


def _norm(value: str) -> str:
    return (value or "").strip().lower().replace("é", "e").replace("è", "e").replace("â", "a")


def find_city(raw: str) -> dict[str, object] | None:
    needle = _norm(raw)
    if not needle:
        return None
    for city in CITIES:
        hay = [_norm(str(city["ar"])), _norm(str(city["fr"]))]
        hay.extend(_norm(a) for a in city.get("aliases") or [])  # type: ignore[union-attr]
        if needle in hay:
            return city
    return None


def city_latin(raw: str) -> str:
    found = find_city(raw)
    if found:
        return str(found["fr"])
    return raw


city_latin = city_latin
find_city = find_city
