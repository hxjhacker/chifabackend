from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

import arabic_reshaper
import qrcode
from bidi.algorithm import get_display
from reportlab.graphics.barcode import code128
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.services.meta_livraison import parcel_code
from app.services.meta_livraison_cities import has_arabic, latin_ville
from app.services.pricing import cents_to_mad
from app.utils.regions import region_id_for_city

PAGE = (100 * mm, 150 * mm)
TZ = ZoneInfo("Africa/Casablanca")
SENDER_NAME = "CHIFA GLOW"
SENDER_CODE = "7605"
SENDER_PHONE = "06-20-86-38-95"
DEPART_HUB = "FES"
TAGLINE = "بإرادتنا حلمكم يوصل"
DISCLAIMER = "META LIVRAISON EST UNIQUEMENT UNE ENTREPRISE DE LIVRAISON."
LABEL_NOT_DISPATCHED = "لا يمكن طباعة بوليصة شحن لطلبية لم يتم إرسالها لشركة التوصيل بعد."
PRINT_HINT = "يجب إرسال الطلبية إلى Meta Livraison أولاً للحصول على رقم التتبع قبل الطباعة."

PACK_NAMES = {
    "quran": "USB القرآن الكريم",
    "kids": "USB تعليم الأطفال",
    "music": "USB الأغاني والموسيقى",
    "educative": "الفلاشة التعليمية الذكية",
    "extra": "مفتاح إضافي بسعر العرض",
}

REGION_HUB = {
    "MA01": "TANGER",
    "MA02": "OUJDA",
    "MA03": "FES",
    "MA04": "RABAT",
    "MA05": "BENI MELLAL",
    "MA06": "CASA",
    "MA07": "MARRAKECH",
    "MA08": "ERRACHIDIA",
    "MA09": "AGADIR",
    "MA10": "GUELMIM",
    "MA11": "LAAYOUNE",
    "MA12": "DAKHLA",
}

HUB_CANON = {
    "casa": "CASA",
    "casablanca": "CASA",
    "fes": "FES",
    "fez": "FES",
    "meknes": "MEKNES",
    "beni mellal": "BENI MELLAL",
    "beni-mellal": "BENI MELLAL",
    "nador": "NADOR",
    "marrakech": "MARRAKECH",
    "agadir": "AGADIR",
    "tanger": "TANGER",
    "tangier": "TANGER",
    "tetouan": "TETOUAN",
    "rabat": "RABAT",
    "oujda": "OUJDA",
    "kenitra": "KENITRA",
    "safi": "SAFI",
    "taza": "TAZA",
    "sefrou": "SEFROU",
    "errachidia": "ERRACHIDIA",
    "tiznit": "TIZNIT",
    "tan tan": "TAN TAN",
    "el jadida": "EL JADIDA",
    "had soualem": "CASA",
    "ouazzane": "OUAZZANE",
    "taounate": "TAOUNATE",
    "chefchaouen": "CHEFCHAOUEN",
    "khenifra": "KHENIFRA",
    "guelmim": "GUELMIM",
    "laayoune": "LAAYOUNE",
    "dakhla": "DAKHLA",
    "ouarzazate": "OUARZAZATE",
    "midelt": "ERRACHIDIA",
}

_FONTS_READY = False


def tracking_of(order: Any) -> str:
    return str(getattr(order, "meta_livraison_code", "") or "").strip()


def _fonts_dir() -> str:
    from pathlib import Path

    return str(Path(__file__).resolve().parent.parent / "assets" / "fonts")


def _ensure_fonts() -> tuple[str, str]:
    global _FONTS_READY
    regular, bold = "Amiri", "Amiri-Bold"
    if not _FONTS_READY:
        folder = _fonts_dir()
        pdfmetrics.registerFont(TTFont(regular, f"{folder}/Amiri-Regular.ttf"))
        pdfmetrics.registerFont(TTFont(bold, f"{folder}/Amiri-Bold.ttf"))
        _FONTS_READY = True
    return regular, bold


def _shape(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if has_arabic(raw):
        return get_display(arabic_reshaper.reshape(raw))
    return raw


def _font_for(text: str, bold: bool = False) -> str:
    if has_arabic(text):
        regular, heavy = _ensure_fonts()
        return heavy if bold else regular
    return "Helvetica-Bold" if bold else "Helvetica"


def _width(text: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(_shape(text), font, size)


def _wrap(text: str, font: str, size: float, max_w: float, max_lines: int = 3) -> list[str]:
    raw = re.sub(r"\s+", " ", str(text or "").strip()) or "—"
    words = raw.split(" ")
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if _width(trial, font, size) <= max_w:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if len(lines) < max_lines:
        lines.append(current)
    lines = lines[:max_lines]
    if _width(lines[-1], font, size) > max_w:
        trimmed = lines[-1]
        while trimmed and _width(trimmed + "…", font, size) > max_w:
            trimmed = trimmed[:-1]
        lines[-1] = (trimmed + "…") if trimmed else "…"
    return lines


def _draw_text(c: canvas.Canvas, text: str, x: float, y: float, size: float, *, bold: bool = False, align: str = "left"):
    font = _font_for(text, bold)
    c.setFont(font, size)
    shaped = _shape(text)
    if align == "right":
        c.drawRightString(x, y, shaped)
    elif align == "center":
        c.drawCentredString(x, y, shaped)
    else:
        c.drawString(x, y, shaped)


def _canon_hub(raw: str) -> str:
    key = re.sub(r"\s+", " ", (raw or "").replace("_", " ").replace("-", " ")).strip().lower()
    if not key:
        return ""
    if key in HUB_CANON:
        return HUB_CANON[key]
    compact = key.replace(" ", "")
    for alias, hub in HUB_CANON.items():
        if alias.replace(" ", "") == compact:
            return hub
    if key.upper() in {v for v in HUB_CANON.values()}:
        return key.upper()
    return ""


def destination_hub(order: Any) -> str:
    shipping = str(getattr(order, "shipping_city", "") or "").strip()
    raw_city = str(getattr(order, "city", "") or "").strip()
    official = latin_ville(shipping, raw_city)
    for candidate in (shipping, official, raw_city):
        text = str(candidate or "").strip()
        if not text:
            continue
        if " - " in text:
            hub = _canon_hub(text.rsplit(" - ", 1)[-1])
            if hub:
                return hub
        dashed = re.search(r"[-–]\s*([A-Za-z][A-Za-z \-]*)$", text)
        if dashed:
            hub = _canon_hub(dashed.group(1))
            if hub and hub not in {"SAHARA", "PORT"}:
                return hub
        hub = _canon_hub(text)
        if hub in HUB_CANON.values():
            return hub
    region = str(getattr(order, "region_id", "") or "").strip().upper() or region_id_for_city(official) or region_id_for_city(raw_city)
    return REGION_HUB.get(region, "FES")


def _phone(order: Any) -> str:
    raw = str(getattr(order, "phone_national", "") or getattr(order, "phone", "") or "")
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("212") and len(digits) >= 12:
        digits = "0" + digits[3:12]
    elif digits.startswith("0") and len(digits) >= 10:
        digits = digits[:10]
    elif len(digits) == 9:
        digits = "0" + digits
    if len(digits) == 10:
        return f"{digits[0:2]}-{digits[2:4]}-{digits[4:6]}-{digits[6:8]}-{digits[8:10]}"
    return raw.strip() or "—"


def _address(order: Any) -> str:
    stored = str(getattr(order, "address", None) or getattr(order, "full_address", None) or "").strip()
    if stored:
        return stored
    bits = [
        str(getattr(order, field, None) or "").strip()
        for field in ("quartier", "street", "building", "landmark")
    ]
    return "، ".join(part for part in bits if part) or "—"


def _ville(order: Any) -> str:
    return latin_ville(
        str(getattr(order, "shipping_city", "") or ""),
        str(getattr(order, "city", "") or ""),
    )


def _goods(order: Any) -> str:
    slug = str(getattr(order, "product_slug", "") or "")
    qty = int(getattr(order, "tier_qty", None) or 1)
    name = PACK_NAMES.get(slug, slug or "Produit")
    parts = [f"{name} × {max(qty, 1)}"]
    extra = str(getattr(order, "cross_sell_slug", "") or "").strip()
    if extra:
        extra_qty = int(getattr(order, "secondary_qty", None) or 1)
        parts.append(f"{PACK_NAMES.get(extra, extra)} × {max(extra_qty, 1)}")
    upsell = str(getattr(order, "upsell_slug", "") or "").strip()
    if upsell and upsell != extra:
        parts.append(PACK_NAMES.get(upsell, upsell))
    return " + ".join(parts)


def _cod(order: Any) -> str:
    value = cents_to_mad(int(getattr(order, "total_cents", 0) or 0))
    if float(value).is_integer():
        return f"{int(value)} MAD"
    return f"{value:.2f} MAD".replace(".00", "")


def _can_open(order: Any) -> bool:
    value = getattr(order, "can_open", None)
    if value is None:
        value = getattr(order, "canOpen", True)
    return bool(value)


def _qr_image(payload: str) -> ImageReader:
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=1)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def _draw_page(c: canvas.Canvas, order: Any) -> None:
    _ensure_fonts()
    w, h = PAGE
    m = 3.2 * mm
    tracking = tracking_of(order)
    hub = destination_hub(order)
    code = parcel_code(str(getattr(order, "id", "") or "ORDER"))
    today = datetime.now(TZ).strftime("%d/%m/%Y")
    notes = str(getattr(order, "courier_notes", "") or "").strip() or "—"
    open_label = "مسموح بالفتح" if _can_open(order) else "ممنوع فتح الطلبية"

    # Header
    logo_s = 11 * mm
    c.setFillColorRGB(0, 0, 0)
    c.rect(m, h - m - logo_s, logo_s, logo_s, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(m + logo_s / 2, h - m - logo_s / 2 - 4, "M")
    c.setFillColorRGB(0, 0, 0)
    brand_x = m + logo_s + 2.2 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(brand_x, h - m - 4.2 * mm, "META")
    c.setFont("Helvetica-Bold", 7.2)
    c.drawString(brand_x, h - m - 7.6 * mm, "LIVRAISON")
    _draw_text(c, TAGLINE, brand_x, h - m - 11.2 * mm, 6.2, bold=True)

    c.setFont("Helvetica", 5.6)
    c.drawString(m, h - m - 16.4 * mm, "Expediteur :")
    c.setFont("Helvetica-Bold", 7)
    c.drawString(m + 22 * mm, h - m - 16.4 * mm, f"{SENDER_NAME} ({SENDER_CODE})")
    c.setFont("Helvetica", 6.2)
    c.drawString(m, h - m - 20.2 * mm, f"Phone : {SENDER_PHONE}")

    right = w - m
    c.setFont("Helvetica", 5.6)
    c.drawRightString(right, h - m - 4.4 * mm, "Depart :")
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(right, h - m - 8.6 * mm, f"HUB {DEPART_HUB}")
    c.setFont("Helvetica", 6.4)
    c.drawRightString(right, h - m - 12.6 * mm, today)

    # Destination banner
    banner_y = h - 36.5 * mm
    banner_h = 12.5 * mm
    c.setFillColorRGB(0, 0, 0)
    c.rect(m, banner_y, w - 2 * m, banner_h, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(w / 2, banner_y + 3.8 * mm, f"HUB {hub}")
    c.setFillColorRGB(0, 0, 0)

    # Body grid
    body_top = banner_y - 2.2 * mm
    body_h = 62 * mm
    left_w = 58 * mm
    gap = 1.6 * mm
    right_w = w - 2 * m - left_w - gap
    left_x = m
    right_x = m + left_w + gap
    body_y = body_top - body_h
    c.setLineWidth(0.7)
    c.rect(left_x, body_y, left_w, body_h, fill=0, stroke=1)
    c.rect(right_x, body_y, right_w, body_h, fill=0, stroke=1)

    fields = [
        ("Destinataire", str(getattr(order, "full_name", "") or "—"), 2),
        ("Telephone", _phone(order), 1),
        ("Ville", _ville(order), 1),
        ("Adresse", _address(order), 3),
        ("Commentaire", notes, 2),
        ("Marchendise", _goods(order), 2),
    ]
    cursor = body_top - 4.2 * mm
    label_x = left_x + 1.8 * mm
    value_w = left_w - 3.6 * mm
    for label, value, max_lines in fields:
        c.setFillColorRGB(0.25, 0.25, 0.25)
        c.setFont("Helvetica", 5.2)
        c.drawString(label_x, cursor, f"{label} :")
        cursor -= 3.4 * mm
        c.setFillColorRGB(0, 0, 0)
        font = _font_for(value, True)
        lines = _wrap(value, font, 7.2, value_w, max_lines)
        for line in lines:
            _draw_text(c, line, label_x, cursor, 7.2, bold=True)
            cursor -= 3.7 * mm
        cursor -= 1.1 * mm

    qr_size = 28 * mm
    qr_x = right_x + (right_w - qr_size) / 2
    qr_y = body_top - qr_size - 4 * mm
    if tracking:
        c.drawImage(_qr_image(tracking), qr_x, qr_y, qr_size, qr_size, preserveAspectRatio=True, mask="auto")
    c.setFont("Helvetica", 5)
    c.drawCentredString(right_x + right_w / 2, qr_y - 3.2 * mm, tracking or "")
    c.setFont("Helvetica-Bold", 12)
    amount = _cod(order)
    c.drawCentredString(right_x + right_w / 2, body_y + 8.5 * mm, amount)
    c.setFont("Helvetica", 5.4)
    c.drawCentredString(right_x + right_w / 2, body_y + 4.4 * mm, "CRBT / COD")

    # COLIS NORMAL
    colis_h = 7.4 * mm
    colis_y = body_y - 2 * mm - colis_h
    c.setFillColorRGB(0, 0, 0)
    c.rect(m, colis_y, w - 2 * m, colis_h, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(w / 2, colis_y + 2.1 * mm, "COLIS NORMAL")
    c.setFillColorRGB(0, 0, 0)

    # Footer barcode + badge + disclaimer
    strip_h = 7 * mm
    badge_w = 9.5 * mm
    bar_x = m
    bar_w = w - 2 * m - badge_w - 1.4 * mm
    bar_y = strip_h + 3.4 * mm
    bar_h = colis_y - bar_y - 2.4 * mm
    c.setLineWidth(0.6)
    c.rect(bar_x, bar_y, bar_w, max(bar_h, 18 * mm), fill=0, stroke=1)
    try:
        available = bar_w - 4 * mm
        bar_width = 0.95
        barcode = code128.Code128(code, barHeight=min(16 * mm, bar_h - 8 * mm), barWidth=bar_width, humanReadable=0)
        while barcode.width > available and bar_width > 0.38:
            bar_width -= 0.05
            barcode = code128.Code128(code, barHeight=min(16 * mm, bar_h - 8 * mm), barWidth=bar_width, humanReadable=0)
        barcode.drawOn(c, bar_x + (bar_w - barcode.width) / 2, bar_y + 7.2 * mm)
    except Exception:
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(bar_x + bar_w / 2, bar_y + 10 * mm, code)
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(bar_x + bar_w / 2, bar_y + 2.4 * mm, code)

    badge_x = w - m - badge_w
    badge_y = bar_y
    badge_h = max(bar_h, 18 * mm)
    c.setFillColorRGB(0, 0, 0)
    c.rect(badge_x, badge_y, badge_w, badge_h, fill=1, stroke=0)
    c.saveState()
    c.setFillColorRGB(1, 1, 1)
    c.translate(badge_x + badge_w / 2, badge_y + badge_h / 2)
    c.rotate(90)
    _draw_text(c, open_label, 0, -2.2, 6.4, bold=True, align="center")
    c.restoreState()

    c.setFillColorRGB(0, 0, 0)
    c.rect(0, 0, w, strip_h, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 4.6)
    c.drawCentredString(w / 2, 2.2 * mm, DISCLAIMER)


def render_label_pdf(orders: list[Any]) -> bytes:
    if not orders:
        raise ValueError("no_labels")
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGE)
    c.setTitle("Chifa Glow — Meta Livraison A6")
    for index, order in enumerate(orders):
        if index:
            c.showPage()
        _draw_page(c, order)
    c.save()
    return buf.getvalue()
