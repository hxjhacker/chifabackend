from __future__ import annotations

import re
import unicodedata

REGION_NAME_TO_ID = {
    "طنجة - تطوان - الحسيمة": "MA01",
    "الشرق": "MA02",
    "فاس - مكناس": "MA03",
    "الرباط - سلا - القنيطرة": "MA04",
    "بني ملال - خنيفرة": "MA05",
    "الدار البيضاء - سطات": "MA06",
    "مراكش - آسفي": "MA07",
    "درعة - تافيلالت": "MA08",
    "سوس - ماسة": "MA09",
    "كلميم - واد نون": "MA10",
    "العيون - الساقية الحمراء": "MA11",
    "الداخلة - وادي الذهب": "MA12",
}

_TNG = "طنجة - تطوان - الحسيمة"
_FES = "فاس - مكناس"
_RBT = "الرباط - سلا - القنيطرة"
_CASA = "الدار البيضاء - سطات"
_MAR = "مراكش - آسفي"
_BML = "بني ملال - خنيفرة"
_AGA = "سوس - ماسة"
_ORI = "الشرق"
_ERD = "درعة - تافيلالت"
_GUL = "كلميم - واد نون"
_LAA = "العيون - الساقية الحمراء"
_DKH = "الداخلة - وادي الذهب"

CITY_TO_REGION = {
    "Tanger": _TNG, "Tetouan": _TNG, "Martil": _TNG, "Cabo Negro": _TNG, "Marina smir": _TNG,
    "Kabila": _TNG, "Bouzaghlal": _TNG, "Bni Rzine": _TNG, "bouanane tetouan": _TNG,
    "Bab Berred": _TNG, "Asilah": _TNG, "Bab Taza": _TNG, "Chefchaouen": _TNG, "Fnideq": _TNG,
    "El Jebeha": _TNG, "M Diq": _TNG, "Khamis Mdiq": _TNG, "Larache": _TNG, "Ksar Sghir": _TNG,
    "Oued Laou": _TNG, "Ksar El Kebir": _TNG, "Ain dorij": _TNG, "Zoumi": _TNG, "Gueznaia": _TNG,
    "Azla": _TNG, "El aanssar": _TNG, "Ounnana": _TNG, "Brikcha": _TNG, "Belyounech": _TNG,
    "Teroual - Ouazzane": _TNG, "Ouazzane": _TNG, "Targuist": _TNG, "Issaguen": _TNG,
    "kaa asras": _TNG, "Amsa": _TNG, "Stehat": _TNG, "sebt mtiwa": _TNG,
    "Beni Ahmed - Chefchaouen": _TNG, "Dardara": _TNG, "Akchour": _TNG, "Dar Akoubaa": _TNG,
    "Ametrass": _TNG, "Al Hoceima": _TNG, "Imzouren": _TNG, "Bni Bouayach": _TNG,
    "Ait youssef": _TNG, "Ain Defali": _TNG, "Ain Beida - Ouazzane": _TNG, "Masmouda": _TNG,
    "Sidi Bousber": _TNG, "Sidi Redouane": _TNG, "Mokrisset": _TNG, "Souk Khemis du Sahel": _TNG,
    "El Aouamra": _TNG, "Dalia": _TNG,
    "FES": _FES, "MEKNES": _FES, "Ain Allah": _FES, "Ain Bida": _FES, "Ain Cheggag": _FES,
    "Ain Taoujdate": _FES, "MHAYA - MEKNES": _FES, "Moulay Yacoub": _FES, "Sidi Harazem": _FES,
    "Kariat Ba Mohamed": _FES, "Ain Leuh": _FES, "Agourai": _FES, "AIN KARMA": _FES,
    "AIT YAAZEM": _FES, "BOUDERBALA": _FES, "Boufakrane": _FES, "BRIDIA": _FES, "DKHISSA": _FES,
    "EL BARAKA - MEKNES": _FES, "ELHajeb": _FES, "Haj Kaddour": _FES, "MEJJAT - Meknes": _FES,
    "Moulay Idriss Zerhoun": _FES, "OUED JDIDA": _FES, "OUISSLAN": _FES,
    "Sabaâ Aïyoun - MEKNES": _FES, "Ain jiri - meknes": _FES, "Boulemane": _FES, "Guigou": _FES,
    "Missour": _FES, "Outat El Haj": _FES, "Imouzzer Marmoucha": _FES, "IFRANE": _FES,
    "AZROU": _FES, "Ayt Yahya Oalla": _FES, "Ait Ali Azrou": _FES, "Sidi Addi": _FES,
    "Timahdite": _FES, "Ras El Ma-FES": _FES, "Ain Chkef - FES": _FES, "Douiyat - FES": _FES,
    "Imouzzer-Kandar - FES": _FES, "Oulad Tayeb - FES": _FES, "Bhalil": _FES,
    "El Menzel - SEFROU": _FES, "Ribate El Kheir": _FES, "Sefrou": _FES, "Azzaba - Sefrou": _FES,
    "Zaouiat Bougrine - Sefrou": _FES, "Senhaja - Sefrou": _FES, "Bir Tam Tam": _FES,
    "Ras Tabouda": _FES, "Ghafsai": _FES, "Taounate": _FES, "Kantra El Ascar": _FES,
    "Zrizer": _FES, "khlalfa": _FES, "Beni Oulid": _FES, "Bouhouda": _FES, "Mernissa": _FES,
    "Thar Es-Souk": _FES, "Fricha - Taounate": _FES, "Ourtzagh - Taounate": _FES,
    "Sahel Boutaher - Taounate": _FES, "Galaz - Taounate": _FES, "Ain Mediouna - Taounate": _FES,
    "Ain Aicha": _FES, "Ouled Daoud - Taounate": _FES, "Tissa": _FES, "Ain Kansara": _FES,
    "Oued Amlil": _FES, "TAHLA": _FES, "TAZA": _FES, "Ajdir": _FES, "Bab Marzouka": _FES,
    "Taddart - Taza": _FES, "Aknoul": _FES, "Tizi Ouasli": _FES, "Skhinate": _FES,
    "RABAT": _RBT, "Sale": _RBT, "Sala Al Jadida": _RBT, "Temara": _RBT, "Tamesna": _RBT,
    "Skhirat": _RBT, "Ain Attig": _RBT, "Ain El Aouda": _RBT, "Sidi Yahya Zaer": _RBT,
    "Harhoura": _RBT, "Mers El Kheir": _RBT, "Sidi Bouknadel": _RBT, "El Arjate": _RBT,
    "Kenitra": _RBT, "Sidi Taibi": _RBT, "Mehdia": _RBT, "Sidi Allal Tazi": _RBT,
    "Sidi Kacem": _RBT, "Sidi slimane": _RBT, "Sidi Yahya El Gharb": _RBT, "SOUK LARBAA": _RBT,
    "Dlalha": _RBT, "Jorf El Melha": _RBT, "Khenichet": _RBT, "Lalla mimouna": _RBT,
    "Mechra Bel Ksiri": _RBT, "Moulay Bousselham": _RBT, "KHEMISSET": _RBT, "Maaziz": _RBT,
    "Oulmes": _RBT, "Rommani": _RBT, "Sidi Allal El Bahraoui": _RBT, "Tiddas": _RBT,
    "TIFLET": _RBT, "Jamaa Houderrane": _RBT, "Ait Belkacem": _RBT, "Mqam Tolba": _RBT,
    "El Khemis des Aït Ouahi": _RBT,
    "Casablanca": _CASA, "had soualem": _CASA, "Mohammedia": _CASA, "Almaz": _CASA,
    "Benslimane": _CASA, "Berrchid": _CASA, "Bouskoura": _CASA, "Bouznika": _CASA,
    "Dar Bouazza": _CASA, "Errahma": _CASA, "Mediouna": _CASA, "Nouaceur": _CASA,
    "Settat": _CASA, "Tit Mellil": _CASA, "Dar 16": _CASA, "Deroua": _CASA,
    "Lahraouyine": _CASA, "La ville verte": _CASA, "Lamkansa - Casa": _CASA,
    "Sidi Massoud": _CASA, "Ain Harrouda": _CASA, "Ben ahmed": _CASA,
    "Plage David Bouznika": _CASA, "Ben Yakhlef": _CASA, "Lkhyayta - Had soualem": _CASA,
    "Lakhyayeta": _CASA, "El Jadida": _CASA, "Sidi Bouzid El Jadida": _CASA,
    "El Haouzia": _CASA, "Sidi Bennour": _CASA, "Khemis Zemamera": _CASA, "Azemmour": _CASA,
    "Bir Jdid": _CASA, "Tnine Chtouka El jadida": _CASA, "Oualidia": _CASA, "Sidi Abbad": _CASA,
    "Oulad Frej": _CASA, "Zaouit Sidi Smail": _CASA, "Jorf Lasfar": _CASA, "Tnine Gharbia": _CASA,
    "Sidi Abderrazzak Khzazna": _CASA, "Oulad Amrane": _CASA, "Moulay Abellah Amghar": _CASA,
    "Sidi Ali Azemmour": _CASA, "Oulad Ghanem": _CASA, "Arba Aounate": _CASA, "Chellalat": _CASA,
    "Sidi Hajjaj": _CASA, "Ouled Mrah": _CASA, "El Gara": _CASA, "El Mansouria": _CASA,
    "El Borouj": _CASA, "Zenata": _CASA, "Sidi Rahal": _CASA, "Tamaris": _CASA, "Louizia": _CASA,
    "Marrakech": _MAR, "Ait Ourir": _MAR, "Tahannaout": _MAR, "Tameslohte": _MAR,
    "Ben Guerir": _MAR, "El Kelaa des Sraghna": _MAR, "Chichaoua": _MAR, "imintanoute": _MAR,
    "Youssoufia": _MAR, "Tamansourt": _MAR, "Souihla": _MAR, "Chouiter": _MAR,
    "Sidi Abdellah Ghiat": _MAR, "OUDAYA Marrakech": _MAR, "Sid L Mokhtar": _MAR,
    "Tamellalt": _MAR, "Belaaguid": _MAR, "Mejjat - Marrakech": _MAR, "Sidi Bou Othmane": _MAR,
    "El Attaouia": _MAR, "Echemmaia": _MAR, "Skhour Rehamna": _MAR, "Mzoudia": _MAR,
    "Ouahat Sidi Brahim": _MAR, "Sid Zouine": _MAR, "Ourika": _MAR, "Lalla Takerkoust": _MAR,
    "Amizmiz": _MAR, "Tassoultante": _MAR, "OULED BEN RAHMOUN": _MAR, "Gouassem": _MAR,
    "Asni": _MAR, "Ouidane MARRAKECH": _MAR, "OULAD HASSOUN": _MAR, "Nzalat Laadam": _MAR,
    "Sebt Saiss": _MAR, "Moulay Brahim": _MAR, "Douar Sidi Moussa": _MAR, "Oulad yahya": _MAR,
    "Douar Soultan": _MAR, "Douar Bouazza": _MAR, "Chrifia": _MAR, "loudaya": _MAR,
    "Safi": _MAR, "Sebt Gzoula": _MAR, "Jamaat shaim": _MAR, "Hrara Safi": _MAR,
    "Had Hrara- Safi": _MAR, "Sidi Bouzid SAFI": _MAR, "Essaouira": _MAR, "Ghazoua": _MAR,
    "Douar Laareb": _MAR, "Sidi Kaouki": _MAR, "Ounagha": _MAR, "Al Morabitin": _MAR,
    "Kchoula": _MAR, "Smimou": _MAR, "Ait Said": _MAR, "Bizdad": _MAR, "Meskala": _MAR,
    "Mejji": _MAR, "Had Draa": _MAR, "Tidzi": _MAR, "Sidi Boulaalam": _MAR, "Boulaalam": _MAR,
    "Birkouate": _MAR, "Lwaiha": _MAR, "Faj Errih": _MAR, "Kraymat": _MAR, "Mramer": _MAR,
    "Tafetachte": _MAR, "Tamanar": _MAR, "Talmest": _MAR, "El Hrarta": _MAR, "El Hanchane": _MAR,
    "Beni Mellal": _BML, "Ougmas": _BML, "Sidi Jaber": _BML, "Oulad Ayad": _BML,
    "Timoulilte": _BML, "Azilal": _BML, "Aguelmous": _BML, "Oued Zem": _BML, "Kasba Tadla": _BML,
    "Ouled Nemma": _BML, "Ouled Mbarek": _BML, "Khenifra": _BML, "Khouribga": _BML,
    "Tighssaline": _BML, "Bejaad": _BML, "El Ksiba - Beni-Mellal": _BML, "Ighrem Laalam": _BML,
    "Fquih Ben Salah": _BML, "Oulad zmam": _BML, "Dar Ould Zidouh": _BML, "Sidi Aissa Ben Ali": _BML,
    "Bni Ayat": _BML, "Mrirt": _BML, "Ait Ishaq": _BML, "Laayayta - Beni Mellal": _BML,
    "Ouaouizeght": _BML, "Ouaoumana": _BML, "Oulad Yaich": _BML, "Oulad Youssef - Beni Mellal": _BML,
    "Ikhourba": _BML, "Oulad Ali - Beni Mellal": _BML, "Foum Oudi - Beni Mellal": _BML,
    "Kahf Nsour": _BML, "Dar Oulad Zidouh": _BML, "Ahl Merbaa - Beni Mellal": _BML,
    "Ahl Souss - Beni Mellal": _BML, "Ain El Ghazi Ali - Beni Mellal": _BML, "Ait Attab": _BML,
    "Ait Tislit": _BML, "Aourir - Beni Mellal": _BML, "Bir Mezoui": _BML, "El Bazzaza": _BML,
    "El Kbab": _BML, "Faryata": _BML, "Foum El Anser": _BML, "Foum Jamaa": _BML, "Foum Zaouia": _BML,
    "Had Bouhsousen": _BML, "Ikhoureba - Beni Mellal": _BML, "Kahf Nssoure": _BML, "Laajana": _BML,
    "Laayayta Oulad Gnaou": _BML, "Lahlalma": _BML, "Lakraza Ouled Said": _BML,
    "Mghila - Beni Mellal": _BML, "Moulay Bouaza": _BML, "Oulad Ali Loued": _BML,
    "Oulad Moussa - Beni Mellal": _BML, "Ouled Rguiaa": _BML, "Ouzoud - Beni Mellal": _BML,
    "Riad Salam-Beni Mellal": _BML, "Tanant": _BML, "Tifrit - Beni Mellal": _BML,
    "Tighasaline": _BML, "Zone Industriell - Beni Mellal": _BML, "Zouair": _BML,
    "Ouled Said El Oued": _BML, "Kaf Nsour": _BML, "Hattane": _BML, "Boujniba": _BML,
    "Boulanouare": _BML, "Ouled Driss - Beni Mellal": _BML, "Al Khalfia": _BML,
    "Oulad ismail - Beni Mellal": _BML, "Ait Ali": _BML, "Ait Rbaa": _BML, "Tanougha": _BML,
    "Adouz - Beni Mellal": _BML, "Aghbalou Ncerdan": _BML, "Ouled Moussa": _BML,
    "El Borj - Khenifra": _BML, "Lahri - khenifra": _BML, "Demnate": _BML, "Afourar": _BML,
    "Zaouiat Cheikh": _BML, "El Kebab": _BML, "Tagzert": _BML, "Souk El Had Des Bradia": _BML,
    "Souk Sebt Oulad Nemma": _BML, "Tachrafat": _BML,
    "Agadir": _AGA, "Aglou": _AGA, "Ait Amira": _AGA, "Ait Baha": _AGA, "Ait melloul": _AGA,
    "Anza": _AGA, "Aourir": _AGA, "Belfaa": _AGA, "Biougra": _AGA, "Aoulouz": _AGA,
    "Houara": _AGA, "Imi Ouaddar": _AGA, "Inchaden": _AGA, "Inezgane": _AGA, "Dcheira": _AGA,
    "Tikiouine": _AGA, "Drarga": _AGA, "Lagfifat": _AGA, "Kasbah El Taher": _AGA, "Massa": _AGA,
    "Oulad Berhil": _AGA, "Oulad Dahou": _AGA, "Sebt El Guerdane": _AGA, "Sidi bibi": _AGA,
    "Temsia": _AGA, "Taroudant": _AGA, "Tarrast": _AGA, "TATA": _AGA, "Tin Mansour": _AGA,
    "Tiznit": _AGA, "Bounaamane - Tiznit": _AGA, "Oulad Teima": _AGA, "Akka": _AGA,
    "Fam El Hisn": _AGA, "Foum zguid": _AGA, "Tissint": _AGA, "Akka Ighane": _AGA,
    "Tafraoute": _AGA, "Taghazout": _AGA, "Taliouine": _AGA, "Tamraght": _AGA,
    "Taddart - Agadir": _AGA,
    "Oujda": _ORI, "NADOR": _ORI, "Beni Ensar": _ORI, "Selouane": _ORI, "Jaadar": _ORI,
    "Zeghanghane": _ORI, "Segangan": _ORI, "AFRA": _ORI, "Al Aaroui": _ORI, "Bouarg": _ORI,
    "Mariouari": _ORI, "Barichino": _ORI, "Tiztoutine": _ORI, "Beni Chiker": _ORI,
    "Farkhana": _ORI, "Beni Sidal Jbel": _ORI, "Kariat Arekmane": _ORI, "Zaio": _ORI,
    "Ouled Settout": _ORI, "Driouch": _ORI, "Ben Taieb": _ORI, "Tafersit": _ORI, "Midar": _ORI,
    "Kassita": _ORI, "Telat Azlaf": _ORI, "Tamsamane": _ORI, "Boudinar": _ORI,
    "Dar El Kebdani": _ORI, "Berkane": _ORI, "AHFIR": _ORI, "Ain Erreggada": _ORI,
    "Ain Reggada": _ORI, "Aklim": _ORI, "Boughriba": _ORI, "Madagh": _ORI, "SAAIDIA": _ORI,
    "Saidia": _ORI, "Beni Drar": _ORI, "Jerada": _ORI, "Ain Beni Mathar": _ORI,
    "Tendrara": _ORI, "Bouarfa": _ORI, "Figuig": _ORI, "Laayoune Charkia": _ORI,
    "El Aioun Sidi Mellouk": _ORI, "Taourirt": _ORI, "Guercif": _ORI, "Tafoughalt": _ORI,
    "Ras El Ma - Nador": _ORI, "SOUK EL GOUR": _ORI, "Tandit": _ORI,
    "Errachidia": _ERD, "Ouarzazate": _ERD, "Tinghir": _ERD, "Zagora": _ERD, "Midelt": _ERD,
    "Agdz": _ERD, "Nkoub Zagora": _ERD, "Tazarine": _ERD, "Boumaln dads": _ERD, "Alnif": _ERD,
    "Kelaat MGouna": _ERD, "Tazenakht": _ERD, "Taznakht": _ERD, "Boudnib": _ERD,
    "Marzouga": _ERD, "Zaida": _ERD, "Tinejdad": _ERD, "Rissani": _ERD, "Riche": _ERD,
    "Boumia": _ERD, "Erfoud": _ERD, "Goulmima - Errachidia": _ERD, "Aoufous": _ERD,
    "Msemrir tinghir": _ERD, "Gourrama": _ERD, "Imilchil": _ERD,
    "Tagounite\u202c zagora": _ERD, "Tamzmout": _ERD,
    "Guelmim": _GUL, "SIDI IFNI": _GUL, "Mirleft": _GUL, "Bouizakarne": _GUL, "TANTAN": _GUL,
    "El Ouatia TAN TAN": _GUL, "Assa": _GUL, "Zag": _GUL,
    "Laayoune Sahara": _LAA, "laayoune Port": _LAA, "EL MARSA LAAYOUNE": _LAA,
    "Boujdour": _LAA, "Essmara SAHARA": _LAA, "Smara": _LAA, "Tarfaya": _LAA, "AKHFNIR": _LAA,
    "Dakhla": _DKH,
}


def _fold(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "").replace("\u202c", "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("-", " ")
    return re.sub(r"\s+", " ", value).strip()


_FOLDED_TO_REGION = {_fold(city): region for city, region in CITY_TO_REGION.items() if _fold(city)}


def get_region_for_city(city_name: str) -> str:
    """Returns official Moroccan Region from official city name."""
    if not city_name:
        return "غير محددة"
    key = city_name.strip()
    if key in CITY_TO_REGION:
        return CITY_TO_REGION[key]
    return _FOLDED_TO_REGION.get(_fold(key), "غير محددة")


def region_id_for_city(city: str) -> str:
    name = get_region_for_city(city)
    return REGION_NAME_TO_ID.get(name, "")
