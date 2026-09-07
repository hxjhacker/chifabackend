from __future__ import annotations

import re
import unicodedata
from difflib import get_close_matches

OFFICIAL_META_CITIES = [
    "Massa", "Mirleft", "Oulad Berhil", "Oulad Dahou", "Sebt El Guerdane", "Sidi bibi",
    "SIDI IFNI", "Temsia", "Taroudant", "Tarrast", "TATA", "Tin Mansour", "Tiznit",
    "Dakhla", "Boujdour", "Essmara SAHARA", "Guelmim", "laayoune Port", "Laayoune Sahara",
    "Bouizakarne", "TANTAN", "Oulad Teima", "IFRANE", "Ougmas", "Sidi Jaber", "Oulad Ayad",
    "Timoulilte", "Azilal", "Aguelmous", "Oued Zem", "Kasba Tadla", "Ouled Nemma",
    "Ouled Mbarek", "Khenifra", "Khouribga", "Tighssaline", "Bejaad", "El Ksiba - Beni-Mellal",
    "Ighrem Laalam", "Fquih Ben Salah", "Oulad zmam", "Dar Ould Zidouh", "Sidi Aissa Ben Ali",
    "Bni Ayat", "Mrirt", "Ait Ishaq", "Laayayta - Beni Mellal", "Ouaouizeght", "Ouaoumana",
    "Oulad Yaich", "Oulad Youssef - Beni Mellal", "Ikhourba", "AZROU", "Ayt Yahya Oalla",
    "Ait Ali Azrou", "Oulad Ali - Beni Mellal", "Foum Oudi - Beni Mellal", "Kahf Nsour",
    "Dar Oulad Zidouh", "Ahl Merbaa - Beni Mellal", "Ahl Souss - Beni Mellal",
    "Ain El Ghazi Ali - Beni Mellal", "Ait Attab", "Ait Tislit", "Aourir - Beni Mellal",
    "Bir Mezoui", "El Bazzaza", "El Kbab", "Faryata", "Foum El Anser", "Foum Jamaa",
    "Foum Zaouia", "Had Bouhsousen", "Ikhoureba - Beni Mellal", "Kahf Nssoure", "Laajana",
    "Laayayta Oulad Gnaou", "Lahlalma", "Lakraza Ouled Said", "Mghila - Beni Mellal",
    "Moulay Bouaza", "Oulad Ali Loued", "Oulad Moussa - Beni Mellal", "Ouled Rguiaa",
    "Ouzoud - Beni Mellal", "Riad Salam-Beni Mellal", "Tanant", "Tifrit - Beni Mellal",
    "Tighasaline", "Zone Industriell - Beni Mellal", "Zouair", "Boulemane", "Guigou",
    "Casablanca", "had soualem", "Mohammedia", "Almaz", "Benslimane", "Berrchid",
    "Bouskoura", "Bouznika", "Dar Bouazza", "Errahma", "Mediouna", "Nouaceur", "Settat",
    "Tit Mellil", "Dar 16", "Deroua", "Lahraouyine", "La ville verte", "Lamkansa - Casa",
    "Sidi Massoud", "Ain Harrouda", "Ben ahmed", "Plage David Bouznika", "Ben Yakhlef",
    "Lkhyayta - Had soualem", "Lakhyayeta", "Mqam Tolba", "El Jadida", "Sidi Bouzid SAFI",
    "Sidi Bouzid El Jadida", "El Haouzia", "Sidi Bennour", "Khemis Zemamera", "Azemmour",
    "Bir Jdid", "Tnine Chtouka El jadida", "Oualidia", "Sidi Abbad", "Oulad Frej",
    "Zaouit Sidi Smail", "Jorf Lasfar", "Tnine Gharbia", "Sidi Abderrazzak Khzazna",
    "Sidi Addi", "Timahdite", "Oulad Amrane", "Moulay Abellah Amghar", "Sidi Ali Azemmour",
    "Oulad Ghanem", "Arba Aounate", "Safi", "Sebt Gzoula", "Jamaat shaim", "Hrara Safi",
    "Had Hrara- Safi", "Smimou", "Ain Allah", "Ain Bida", "Ain Cheggag", "Ain Taoujdate",
    "MHAYA - MEKNES", "Moulay Yacoub", "Sidi Harazem", "Kariat Ba Mohamed", "KHEMISSET",
    "Maaziz", "Oulmes", "Rommani", "Sidi Allal El Bahraoui", "Tiddas", "TIFLET",
    "Jamaa Houderrane", "Ait Belkacem", "Chellalat", "Sidi Hajjaj", "Marrakech", "Ait Ourir",
    "Tahannaout", "Agadir", "Aglou", "Ait Amira", "Ait Baha", "Ait melloul", "Anza",
    "Aourir", "Belfaa", "Biougra", "Akka", "Aoulouz", "Fam El Hisn", "Foum zguid",
    "Houara", "Imi Ouaddar", "Inchaden", "Inezgane", "Tameslohte", "Ben Guerir",
    "El Kelaa des Sraghna", "Chichaoua", "imintanoute", "Youssoufia", "Tamansourt",
    "Souihla", "Chouiter", "Sidi Abdellah Ghiat", "OUDAYA Marrakech", "Sid L Mokhtar",
    "Tamellalt", "Belaaguid", "Mejjat - Marrakech", "Sidi Bou Othmane", "El Attaouia",
    "Echemmaia", "Skhour Rehamna", "Mzoudia", "Ouahat Sidi Brahim", "Sid Zouine", "Ourika",
    "Lalla Takerkoust", "Amizmiz", "Tassoultante", "OULED BEN RAHMOUN", "Gouassem",
    "Taznakht", "Asni", "Ouidane MARRAKECH", "OULAD HASSOUN", "Nzalat Laadam", "Sebt Saiss",
    "Moulay Brahim", "Douar Sidi Moussa", "Oulad yahya", "Douar Soultan", "Douar Bouazza",
    "Chrifia", "loudaya", "Dcheira", "Tikiouine", "Drarga", "Assa", "Lagfifat",
    "Kasbah El Taher", "Bounaamane - Tiznit", "Tarfaya", "Essaouira", "Agdz", "Nkoub Zagora",
    "Tazarine", "Ouarzazate", "Tinghir", "Boumaln dads", "Alnif", "Kelaat MGouna",
    "Tissint", "Akka Ighane", "Tazenakht", "Ghazoua", "Douar Laareb", "Sidi Kaouki",
    "Ounagha", "Al Morabitin", "Kchoula", "Ain Leuh", "Agourai", "AIN KARMA", "AIT YAAZEM",
    "BOUDERBALA", "Boufakrane", "BRIDIA", "DKHISSA", "EL BARAKA - MEKNES", "ELHajeb",
    "Haj Kaddour", "MEJJAT - Meknes", "Ait Said", "Bizdad", "Meskala", "Mejji", "Had Draa",
    "Tidzi", "Sidi Boulaalam", "Boulaalam", "Birkouate", "Lwaiha", "Faj Errih", "Kraymat",
    "Mramer", "AKHFNIR", "MEKNES", "Moulay Idriss Zerhoun", "OUED JDIDA", "OUISSLAN",
    "Sabaâ Aïyoun - MEKNES", "Ain jiri - meknes", "Missour", "Outat El Haj",
    "Imouzzer Marmoucha", "Oujda", "NADOR", "Beni Ensar", "Selouane", "Ouled Said El Oued",
    "Kaf Nsour", "Hattane", "Boujniba", "Boulanouare", "Ouled Driss - Beni Mellal",
    "Al Khalfia", "Ouled Mrah", "Oulad ismail - Beni Mellal", "Ait Ali", "Ait Rbaa",
    "Tanougha", "Adouz - Beni Mellal", "Aghbalou Ncerdan", "Ouled Moussa",
    "El Borj - Khenifra", "Lahri - khenifra", "Demnate", "Beni Mellal", "Jaadar",
    "Zeghanghane", "Segangan", "AFRA", "Al Aaroui", "Bouarg", "Mariouari", "Barichino",
    "Tiztoutine", "Beni Chiker", "Farkhana", "Beni Sidal Jbel", "Kariat Arekmane", "Zaio",
    "Ouled Settout", "Driouch", "Ben Taieb", "Tafersit", "Midar", "Kassita", "Telat Azlaf",
    "Tamsamane", "Boudinar", "Dar El Kebdani", "Berkane", "AHFIR", "Ain Erreggada",
    "Ain Reggada", "Aklim", "Boughriba", "Madagh", "SAAIDIA", "Saidia", "Beni Drar",
    "Jerada", "Ain Beni Mathar", "Tendrara", "Bouarfa", "Figuig", "Laayoune Charkia",
    "El Aioun Sidi Mellouk", "Taourirt", "Guercif", "Tafoughalt", "Ras El Ma - Nador",
    "Dlalha", "Jorf El Melha", "Khenichet", "Lalla mimouna", "Mechra Bel Ksiri",
    "Moulay Bousselham", "RABAT", "Sidi Kacem", "Sidi slimane", "Sidi Yahya El Gharb",
    "SOUK LARBAA", "El Arjate", "Sale", "Sala Al Jadida", "Temara", "Tamesna", "Skhirat",
    "Ain Attig", "Ain El Aouda", "Sidi Yahya Zaer", "Harhoura", "Mers El Kheir",
    "Sidi Bouknadel", "Kenitra", "Sidi Taibi", "Mehdia", "Sidi Allal Tazi",
    "El Khemis des Aït Ouahi", "El Ouatia TAN TAN", "Zagora", "Zag", "El Hrarta",
    "El Hanchane", "EL MARSA LAAYOUNE", "Afourar", "Zaouiat Cheikh", "El Kebab", "El Gara",
    "El Mansouria", "El Borouj", "Zenata", "Ras El Ma-FES", "Ain Chkef - FES",
    "Douiyat - FES", "FES", "Imouzzer-Kandar - FES", "Oulad Tayeb - FES", "Bhalil",
    "El Menzel - SEFROU", "Ribate El Kheir", "Sefrou", "Azzaba - Sefrou",
    "Zaouiat Bougrine - Sefrou", "Senhaja - Sefrou", "Bir Tam Tam", "Ras Tabouda", "Boudnib",
    "Marzouga", "Zaida", "Tinejdad", "Rissani", "Riche", "Boumia", "Erfoud", "Errachidia",
    "Goulmima - Errachidia", "Aoufous", "Msemrir tinghir", "Midelt", "Gourrama", "Imilchil",
    "Ouazzane", "Tanger", "Martil", "Cabo Negro", "Marina smir", "Kabila", "Bouzaghlal",
    "Bni Rzine", "bouanane tetouan", "Bab Berred", "Asilah", "Bab Taza", "Chefchaouen",
    "Fnideq", "El Jebeha", "M Diq", "Larache", "Ksar Sghir", "Oued Laou", "Tetouan",
    "Ksar El Kebir", "Ain dorij", "Zoumi", "Gueznaia", "Azla", "El aanssar", "Khamis Mdiq",
    "Ounnana", "Brikcha", "Belyounech", "Teroual - Ouazzane", "Targuist", "Issaguen",
    "kaa asras", "Amsa", "Stehat", "Ghafsai", "Taounate", "Kantra El Ascar", "Zrizer",
    "khlalfa", "sebt mtiwa", "Beni Oulid", "Bouhouda", "Mernissa", "Thar Es-Souk",
    "Fricha - Taounate", "Tafraoute", "Taghazout", "Taliouine", "Tamraght", "Taddart - Agadir",
    "Tagounite\u202c zagora", "Smara", "Tafetachte", "Tamanar", "Talmest", "Tamzmout",
    "Tagzert", "Souk El Had Des Bradia", "Souk Sebt Oulad Nemma", "Tachrafat", "Sidi Rahal",
    "Tamaris", "Skhinate", "SOUK EL GOUR", "Tandit", "El Aouamra", "Dalia",
    "Beni Ahmed - Chefchaouen", "Dardara", "Akchour", "Dar Akoubaa", "Ametrass",
    "Al Hoceima", "Imzouren", "Bni Bouayach", "Ait youssef", "Ain Defali",
    "Ain Beida - Ouazzane", "Masmouda", "Sidi Bousber", "Sidi Redouane", "Mokrisset",
    "Souk Khemis du Sahel", "Louizia", "Ourtzagh - Taounate", "Sahel Boutaher - Taounate",
    "Galaz - Taounate", "Ain Mediouna - Taounate", "Ain Aicha", "Ouled Daoud - Taounate",
    "Tissa", "Ain Kansara", "Oued Amlil", "TAHLA", "TAZA", "Ajdir", "Bab Marzouka",
    "Taddart - Taza", "Aknoul", "Tizi Ouasli",
]

CITY_ALIASES = {
    "casa": "Casablanca",
    "casablanca": "Casablanca",
    "dar beida": "Casablanca",
    "dar lbida": "Casablanca",
    "الدار البيضاء": "Casablanca",
    "الدار البيضا": "Casablanca",
    "الدارلبيضاء": "Casablanca",
    "البيضاء": "Casablanca",
    "كازا": "Casablanca",
    "كازابلانكا": "Casablanca",
    "rabat": "RABAT",
    "الرباط": "RABAT",
    "رباط": "RABAT",
    "fes": "FES",
    "fez": "FES",
    "fas": "FES",
    "فاس": "FES",
    "marrakech": "Marrakech",
    "marrakesh": "Marrakech",
    "merrakech": "Marrakech",
    "مراكش": "Marrakech",
    "مراكش الحمراء": "Marrakech",
    "tanger": "Tanger",
    "tangier": "Tanger",
    "tanja": "Tanger",
    "طنجة": "Tanger",
    "meknes": "MEKNES",
    "meknès": "MEKNES",
    "مكناس": "MEKNES",
    "sale": "Sale",
    "salé": "Sale",
    "سلا": "Sale",
    "agadir": "Agadir",
    "أكادير": "Agadir",
    "اكادير": "Agadir",
    "kenitra": "Kenitra",
    "kénitra": "Kenitra",
    "القنيطرة": "Kenitra",
    "قنيطرة": "Kenitra",
    "oujda": "Oujda",
    "وجدة": "Oujda",
    "tetouan": "Tetouan",
    "tétouan": "Tetouan",
    "تطوان": "Tetouan",
    "temara": "Temara",
    "تمارة": "Temara",
    "mohammedia": "Mohammedia",
    "المحمدية": "Mohammedia",
    "el jadida": "El Jadida",
    "jadida": "El Jadida",
    "الجديدة": "El Jadida",
    "beni mellal": "Beni Mellal",
    "benimellal": "Beni Mellal",
    "بني ملال": "Beni Mellal",
    "nador": "NADOR",
    "الناظور": "NADOR",
    "ناظور": "NADOR",
    "khouribga": "Khouribga",
    "خريبكة": "Khouribga",
    "settat": "Settat",
    "سطات": "Settat",
    "berrechid": "Berrchid",
    "berrchid": "Berrchid",
    "برشيد": "Berrchid",
    "larache": "Larache",
    "العرائش": "Larache",
    "khemisset": "KHEMISSET",
    "khémisset": "KHEMISSET",
    "الخميسات": "KHEMISSET",
    "guelmim": "Guelmim",
    "كلميم": "Guelmim",
    "berkane": "Berkane",
    "بركان": "Berkane",
    "taza": "TAZA",
    "تازة": "TAZA",
    "التازة": "TAZA",
    "safi": "Safi",
    "اسفي": "Safi",
    "آسفي": "Safi",
    "asfi": "Safi",
    "essaouira": "Essaouira",
    "الصويرة": "Essaouira",
    "الصويره": "Essaouira",
    "ouarzazate": "Ouarzazate",
    "ورزازات": "Ouarzazate",
    "errachidia": "Errachidia",
    "الرشيدية": "Errachidia",
    "laayoune": "Laayoune Sahara",
    "laayoune sahara": "Laayoune Sahara",
    "العيون": "Laayoune Sahara",
    "dakhla": "Dakhla",
    "الداخلة": "Dakhla",
    "inezgane": "Inezgane",
    "انزكان": "Inezgane",
    "إنزكان": "Inezgane",
    "ait melloul": "Ait melloul",
    "أيت ملول": "Ait melloul",
    "taroudant": "Taroudant",
    "تارودانت": "Taroudant",
    "tiznit": "Tiznit",
    "تيزنيت": "Tiznit",
    "ksar el kebir": "Ksar El Kebir",
    "القصر الكبير": "Ksar El Kebir",
    "fnideq": "Fnideq",
    "الفنيدق": "Fnideq",
    "mdiq": "M Diq",
    "m diq": "M Diq",
    "المضيق": "M Diq",
    "chefchaouen": "Chefchaouen",
    "شفشاون": "Chefchaouen",
    "al hoceima": "Al Hoceima",
    "الحسيمة": "Al Hoceima",
    "taourirt": "Taourirt",
    "تاوريرت": "Taourirt",
    "skhirat": "Skhirat",
    "الصخيرات": "Skhirat",
    "bouznika": "Bouznika",
    "بوزنيقة": "Bouznika",
    "bouskoura": "Bouskoura",
    "بوسكورة": "Bouskoura",
    "dar bouazza": "Dar Bouazza",
    "دار بوعزة": "Dar Bouazza",
    "had soualem": "had soualem",
    "حد السوالم": "had soualem",
    "youssoufia": "Youssoufia",
    "اليوسفية": "Youssoufia",
    "khenifra": "Khenifra",
    "خنيفرة": "Khenifra",
    "azrou": "AZROU",
    "أزرو": "AZROU",
    "ifrane": "IFRANE",
    "إفران": "IFRANE",
    "midelt": "Midelt",
    "ميدلت": "Midelt",
    "tinghir": "Tinghir",
    "تنغير": "Tinghir",
    "zagora": "Zagora",
    "زاكورة": "Zagora",
    "tantan": "TANTAN",
    "طانطان": "TANTAN",
    "sidi kacem": "Sidi Kacem",
    "سيدي قاسم": "Sidi Kacem",
    "sidi slimane": "Sidi slimane",
    "سيدي سليمان": "Sidi slimane",
    "ouazzane": "Ouazzane",
    "وزان": "Ouazzane",
    "taounate": "Taounate",
    "تاونات": "Taounate",
    "sefrou": "Sefrou",
    "صفرو": "Sefrou",
    "guercif": "Guercif",
    "جرسيف": "Guercif",
    "jerada": "Jerada",
    "جرادة": "Jerada",
    "figuig": "Figuig",
    "فجيج": "Figuig",
    "smara": "Smara",
    "السمارة": "Smara",
    "boujdour": "Boujdour",
    "بوجدور": "Boujdour",
    "إيموزار كندر": "Imouzzer-Kandar - FES",
    "ايموزار كندر": "Imouzzer-Kandar - FES",
    "إيموزار كندار": "Imouzzer-Kandar - FES",
    "ايموزار كندار": "Imouzzer-Kandar - FES",
    "إيموزار-كندر": "Imouzzer-Kandar - FES",
    "ايموزار-كندر": "Imouzzer-Kandar - FES",
    "imouzzer kandar": "Imouzzer-Kandar - FES",
    "imouzzer-kandar": "Imouzzer-Kandar - FES",
    "imouzar kandar": "Imouzzer-Kandar - FES",
    "imouzzer kender": "Imouzzer-Kandar - FES",
    "ait sebaa": "Sefrou",
    "ait sebaa lajrouf": "Sefrou",
    "ait sebaa lajrouf sefrou": "Sefrou",
    "lajrouf sefrou": "Sefrou",
    "lajrouf": "Sefrou",
    "آيت السبع": "Sefrou",
    "ايت السبع": "Sefrou",
    "آيت سبع": "Sefrou",
    "الجروف": "Sefrou",
    "أولاد الطيب": "Oulad Tayeb - FES",
    "اولاد الطيب": "Oulad Tayeb - FES",
    "دويات": "Douiyat - FES",
    "عين الشقف": "Ain Chkef - FES",
    "بهاليل": "Bhalil",
    "إيموزار مرموشة": "Imouzzer Marmoucha",
    "ايموزار مرموشة": "Imouzzer Marmoucha",
}


_AR_DIAC = re.compile(r"[\u064B-\u065F\u0670\u0640]")
_NON_WORD = re.compile(r"[^a-z0-9\u0600-\u06ff]+")
_SPACES = re.compile(r"\s+")
_LATIN_ARTICLE = re.compile(r"\b(?:al|el|le|la|les|the|l)\b")
_VOWELS = re.compile(r"[aeiouy]")
_ARABIC_CHAR = re.compile(r"[\u0600-\u06ff]")
_AR_TO_LATIN = {
    "ا": "a",
    "ب": "b",
    "ت": "t",
    "ث": "t",
    "ج": "j",
    "ح": "h",
    "خ": "kh",
    "د": "d",
    "ذ": "d",
    "ر": "r",
    "ز": "z",
    "س": "s",
    "ش": "ch",
    "ص": "s",
    "ض": "d",
    "ط": "t",
    "ظ": "z",
    "ع": "a",
    "غ": "gh",
    "ف": "f",
    "ق": "q",
    "ك": "k",
    "ل": "l",
    "م": "m",
    "ن": "n",
    "ه": "h",
    "و": "ou",
    "ي": "i",
    "ء": "",
}


def normalize_arabic_text(text: str) -> str:
    if not text:
        return ""
    s = text.strip()
    for a in ["إ", "أ", "آ", "ٱ"]:
        s = s.replace(a, "ا")
    s = s.replace("ى", "ي").replace("ة", "ه")
    s = re.sub(r"[\u064B-\u065F\u0670]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def fold_city(text: str) -> str:
    value = (text or "").replace("\u202c", "").replace("\u200f", "").replace("\u200e", "").replace("\ufeff", "")
    value = normalize_arabic_text(value)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = _AR_DIAC.sub("", value)
    value = value.replace("ؤ", "و").replace("ئ", "ي")
    value = value.casefold()
    value = _LATIN_ARTICLE.sub(" ", value)
    if value.startswith("ال"):
        value = value[2:]
    glued = re.match(r"^(al|el)([a-z].+)$", value)
    if glued and len(glued.group(2)) >= 4:
        value = glued.group(2)
    value = _NON_WORD.sub(" ", value)
    return _SPACES.sub(" ", value).strip()


def romanize_arabic(text: str) -> str:
    value = fold_city(text)
    if not value:
        return ""
    if not _ARABIC_CHAR.search(value):
        return value
    if value.startswith("اي"):
        value = "i" + value[2:]
    chars: list[str] = []
    for ch in value:
        if ch == " ":
            chars.append(" ")
        elif ch in _AR_TO_LATIN:
            chars.append(_AR_TO_LATIN[ch])
        elif "a" <= ch <= "z" or ch.isdigit():
            chars.append(ch)
    return _SPACES.sub(" ", "".join(chars)).strip()


def _skeleton(text: str) -> str:
    compact = text.replace(" ", "")
    compact = _VOWELS.sub("", compact)
    return re.sub(r"(.)\1+", r"\1", compact)


def _token_skeletons(text: str) -> tuple[str, ...]:
    return tuple(skel for tok in text.split() if (skel := _skeleton(tok)))


def _index_official() -> tuple[dict[str, str], list[str], dict[str, str], list[tuple[str, tuple[str, ...]]]]:
    folded: dict[str, str] = {}
    keys: list[str] = []
    arabic_norm: dict[str, str] = {}
    token_index: list[tuple[str, tuple[str, ...]]] = []
    for official in OFFICIAL_META_CITIES:
        variants = [official, official.split(" - ", 1)[0], official.split(",", 1)[0]]
        for variant in variants:
            key = fold_city(variant)
            if not key:
                continue
            folded.setdefault(key, official)
            if key not in keys:
                keys.append(key)
        latin = fold_city(official.split(" - ", 1)[0])
        tokens = _token_skeletons(latin)
        if tokens:
            token_index.append((official, tokens))
    for alias, official in CITY_ALIASES.items():
        key = fold_city(alias)
        if key:
            folded[key] = official
            if key not in keys:
                keys.append(key)
        ar_key = normalize_arabic_text(alias)
        if ar_key:
            arabic_norm[ar_key] = official
    return folded, keys, arabic_norm, token_index


_FOLD_TO_OFFICIAL, _FOLD_KEYS, _ARABIC_NORM_TO_OFFICIAL, _OFFICIAL_TOKEN_SKELS = _index_official()
_COMPACT_TO_OFFICIAL = {
    key.replace(" ", ""): official
    for key, official in _FOLD_TO_OFFICIAL.items()
    if key.replace(" ", "")
}


def _lookup_folded(folded: str) -> str:
    if not folded:
        return ""
    exact = _FOLD_TO_OFFICIAL.get(folded)
    if exact:
        return exact
    compact = folded.replace(" ", "")
    compact_hit = _COMPACT_TO_OFFICIAL.get(compact)
    if compact_hit:
        return compact_hit
    close = get_close_matches(folded, _FOLD_KEYS, n=1, cutoff=0.78)
    if not close and len(folded) >= 4:
        close = get_close_matches(folded, _FOLD_KEYS, n=1, cutoff=0.68)
    if close:
        return _FOLD_TO_OFFICIAL[close[0]]
    compact_keys = list(_COMPACT_TO_OFFICIAL)
    if compact and len(compact) >= 6:
        close_compact = get_close_matches(compact, compact_keys, n=1, cutoff=0.78)
        if close_compact:
            return _COMPACT_TO_OFFICIAL[close_compact[0]]
    starts = [key for key in _FOLD_KEYS if key.startswith(folded) or folded.startswith(key)]
    if len(starts) == 1 and min(len(starts[0]), len(folded)) >= 4:
        return _FOLD_TO_OFFICIAL[starts[0]]
    return ""


def _lookup_skeleton(latin: str) -> str:
    tokens = _token_skeletons(latin)
    if not tokens:
        return ""
    hits: list[tuple[int, str]] = []
    for official, official_tokens in _OFFICIAL_TOKEN_SKELS:
        if not all(token in official_tokens for token in tokens):
            continue
        if len(tokens) == 1 and official_tokens != tokens:
            continue
        extra = len(official_tokens) - len(tokens)
        hits.append((extra, official))
    if not hits:
        return ""
    unique = {official for _, official in hits}
    if len(unique) == 1:
        return hits[0][1]
    hits.sort()
    best_extra = hits[0][0]
    best = [official for extra, official in hits if extra == best_extra]
    if len(set(best)) == 1:
        return best[0]
    return ""


def resolve_meta_city(raw: str) -> str:
    original = " ".join((raw or "").split())
    if not original:
        return ""

    arabic_norm = normalize_arabic_text(original)
    alias_hit = _ARABIC_NORM_TO_OFFICIAL.get(arabic_norm)
    if alias_hit:
        return alias_hit

    folded = fold_city(original)
    hit = _lookup_folded(folded)
    if hit:
        return hit

    roman = romanize_arabic(original)
    if roman and roman != folded:
        hit = _lookup_folded(roman)
        if hit:
            return hit
        hit = _lookup_skeleton(roman)
        if hit:
            return hit
    elif folded:
        hit = _lookup_skeleton(folded)
        if hit:
            return hit

    parts = folded.split()
    if len(parts) >= 2:
        for i in range(1, len(parts)):
            tail = " ".join(parts[i:])
            hit = _lookup_folded(tail)
            if hit:
                return hit

    return original


_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
FALLBACK_VILLE = "RABAT"
OFFICIAL_SET = set(OFFICIAL_META_CITIES)


def has_arabic(text: str) -> bool:
    return bool(_ARABIC_RE.search(text or ""))


def is_official_meta_city(text: str) -> bool:
    return (text or "").strip() in OFFICIAL_SET


def latin_ville(*candidates: str) -> str:
    for candidate in candidates:
        text = (candidate or "").strip()
        if not text:
            continue
        if is_official_meta_city(text) and not has_arabic(text):
            return text
        resolved = resolve_meta_city(text)
        if is_official_meta_city(resolved) and not has_arabic(resolved):
            return resolved
    return FALLBACK_VILLE
