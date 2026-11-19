from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import arabic_reshaper
import qrcode
from bidi.algorithm import get_display
from qrcode.constants import ERROR_CORRECT_M
from reportlab.graphics.barcode import code128
from reportlab.lib.colors import Color, black, white
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.services.carriers import CARRIER_QUICK, normalize_carrier
from app.services.city_tarifs import TarifIndex
from app.services.meta_livraison import parcel_code
from app.services.meta_livraison_cities import has_arabic, latin_ville
from app.services.pricing import cents_to_mad
from app.utils.regions import region_id_for_city

PAGE = (100 * mm, 100 * mm)
TZ = ZoneInfo("Africa/Casablanca")
META_SENDER_NAME = "CHIFA GLOW"
META_SENDER_CODE = "7605"
META_SENDER_PHONE = "06-20-86-38-95"
META_DEPART_HUB = "FES"
QUICK_SENDER_NAME = "chifaglow"
QUICK_SENDER_CODE = "7513"
QUICK_SENDER_PHONE = "0644183475"
QUICK_EXPEDITION = "CASA"
DEFAULT_VENDOR_NAME = "CHIFA GLOW"
DEFAULT_VENDOR_PHONE = "0640108706"
TAGLINE = "بإرادتنا حلمكم يوصل"
DISCLAIMER = "META LIVRAISON EST UNIQUEMENT UNE ENTREPRISE DE LIVRAISON."
BLUE = Color(0.12, 0.29, 0.56)
NAVY = Color(0.09, 0.23, 0.43)
GREEN = Color(0.18, 0.61, 0.29)

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

_FONTS: tuple[str, str] | None = None
log = logging.getLogger(__name__)


def tracking_of(order: Any) -> str:
    from app.services.carriers import normalize_carrier
    from app.services.carriers.quick import is_dummy_parcel_code, quick_client_code

    code = str(getattr(order, "meta_livraison_code", None) or getattr(order, "tracking_number", None) or "").strip()
    if normalize_carrier(getattr(order, "carrier", None)) == "quick_livraison" and is_dummy_parcel_code(code):
        return quick_client_code(order) or code
    return code


def _font_files() -> list[tuple[Path, Path]]:
    folder = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    return [
        # The Docker image installs these. Noto has reliable Arabic presentation
        # forms, Latin glyphs and both Western/Arabic-Indic digits.
        (Path("/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"), Path("/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf")),
        (Path("/usr/share/fonts/opentype/noto/NotoSansArabic-Regular.ttf"), Path("/usr/share/fonts/opentype/noto/NotoSansArabic-Bold.ttf")),
        (Path("/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf"), Path("/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf")),
        # Bundled fallback means PDF generation does not depend solely on the OS.
        (folder / "Amiri-Regular.ttf", folder / "Amiri-Bold.ttf"),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
        (Path("C:/Windows/Fonts/tahoma.ttf"), Path("C:/Windows/Fonts/tahomabd.ttf")),
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
        (Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"), Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")),
    ]


def _font_probe() -> str:
    """Characters the embedded label font must support after Arabic shaping."""
    arabic = "الطلبية الاسم المدينة العنوان المنتوج المبلغ إستبدال فاطمة آمنة ٠١٢٣٤٥٦٧٨٩"
    try:
        arabic = get_display(arabic_reshaper.reshape(arabic))
    except Exception:
        pass
    return f"{arabic} ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789 -:<>/،—"


def _font_missing_glyphs(font_name: str) -> list[str]:
    font = pdfmetrics.getFont(font_name)
    widths = getattr(getattr(font, "face", None), "charWidths", {}) or {}
    if not widths:
        return list(_font_probe())
    return sorted({char for char in _font_probe() if not char.isspace() and ord(char) not in widths})


def _ensure_fonts() -> tuple[str, str]:
    global _FONTS
    if _FONTS:
        return _FONTS
    attempted: list[str] = []
    for index, (reg_path, bold_path) in enumerate(_font_files()):
        if not reg_path.exists():
            attempted.append(f"{reg_path} (missing)")
            continue
        try:
            regular = f"LabelSans-{index}"
            bold = f"LabelSans-Bold-{index}"
            heavy = bold_path if bold_path.exists() else reg_path
            pdfmetrics.registerFont(TTFont(regular, str(reg_path), validate=1))
            pdfmetrics.registerFont(TTFont(bold, str(heavy), validate=1))
            missing = sorted(set(_font_missing_glyphs(regular) + _font_missing_glyphs(bold)))
            if missing:
                preview = " ".join(f"U+{ord(char):04X}" for char in missing[:12])
                attempted.append(f"{reg_path} (missing glyphs: {preview})")
                continue
            pdfmetrics.registerFontFamily(
                f"LabelSansFamily-{index}",
                normal=regular,
                bold=bold,
                italic=regular,
                boldItalic=bold,
            )
            _FONTS = (regular, bold)
            log.info("Shipping-label fonts embedded: regular=%s bold=%s", reg_path, heavy)
            return _FONTS
        except Exception as exc:
            attempted.append(f"{reg_path} ({type(exc).__name__}: {exc})")
            continue
    detail = "; ".join(attempted) or "no font candidates configured"
    raise RuntimeError(
        "No embeddable Unicode font with Arabic, Latin and digit coverage is available "
        f"for shipping labels. Checked: {detail}"
    )


def verify_label_fonts() -> dict[str, str]:
    """Build/startup probe used by Docker and operational diagnostics."""
    regular, bold = _ensure_fonts()
    if _font_missing_glyphs(regular) or _font_missing_glyphs(bold):
        raise RuntimeError("Configured shipping-label font failed Unicode coverage verification")
    return {"regular": regular, "bold": bold}


def verify_unicode_pdf_embedding() -> dict[str, int | str]:
    """Render a mixed Unicode probe and assert that its TTF program is embedded."""
    regular, bold = _ensure_fonts()
    probe = BytesIO()
    test_canvas = canvas.Canvas(probe, pagesize=(60 * mm, 25 * mm))
    _draw_text(test_canvas, "الاسم: فاطمة — المدينة: الدار البيضاء", 3 * mm, 16 * mm, 10, bold=True)
    _draw_text(test_canvas, "Téléphone: 0640108706 — ٠١٢٣٤٥٦٧٨٩", 3 * mm, 8 * mm, 9)
    test_canvas.save()
    payload = probe.getvalue()
    if len(payload) < 1000 or b"/FontFile2" not in payload:
        raise RuntimeError("Shipping-label Unicode smoke PDF did not contain an embedded TrueType font")
    return {"regular": regular, "bold": bold, "pdf_bytes": len(payload)}


def _shape(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if has_arabic(raw):
        try:
            return get_display(arabic_reshaper.reshape(raw))
        except Exception:
            return raw
    return raw


def _font_for(text: str, bold: bool = False) -> str:
    regular, heavy = _ensure_fonts()
    return heavy if bold else regular


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


def _draw_text(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    size: float,
    *,
    bold: bool = False,
    align: str = "left",
) -> None:
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
    if key.upper() in set(HUB_CANON.values()):
        return key.upper()
    return ""


def destination_hub(order: Any, tarifs: TarifIndex | None = None) -> str:
    shipping = str(getattr(order, "shipping_city", "") or "").strip()
    raw_city = str(getattr(order, "city", "") or "").strip()
    official = latin_ville(shipping, raw_city)
    if tarifs:
        hub = tarifs.hub_for(shipping, official, raw_city)
        if hub:
            return re.sub(r"^HUB\s+", "", hub, flags=re.IGNORECASE).strip().upper() or hub
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
    if REGION_HUB.get(region):
        return REGION_HUB[region]
    named = (official or raw_city).strip().upper()
    return named or "FES"


def _national_digits(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("212") and len(digits) >= 12:
        return "0" + digits[3:12]
    if digits.startswith("0") and len(digits) >= 10:
        return digits[:10]
    if len(digits) == 9:
        return "0" + digits
    return digits


def _phone(order: Any, pattern: str = "meta") -> str:
    raw = str(getattr(order, "phone_national", "") or getattr(order, "phone", "") or "")
    digits = _national_digits(raw)
    if len(digits) != 10:
        return raw.strip() or "—"
    if pattern == "quick":
        return f"{digits[0:2]}-{digits[2:5]}-{digits[5:8]}-{digits[8:10]}"
    return f"{digits[0:2]}-{digits[2:4]}-{digits[4:6]}-{digits[6:8]}-{digits[8:10]}"


def _address(order: Any) -> str:
    stored = str(getattr(order, "address", None) or getattr(order, "full_address", None) or "").strip()
    if stored:
        return stored
    bits = [str(getattr(order, field, None) or "").strip() for field in ("quartier", "street", "building", "landmark")]
    return "، ".join(part for part in bits if part) or "—"


def _ville(order: Any) -> str:
    return latin_ville(
        str(getattr(order, "shipping_city", "") or ""),
        str(getattr(order, "city", "") or ""),
    ).upper() or "—"


def _sku_lines(order: Any) -> list[tuple[str, int]]:
    slug = str(getattr(order, "product_slug", "") or "").strip() or "Produit"
    qty = int(getattr(order, "tier_qty", None) or getattr(order, "quantity", None) or 1)
    lines = [(slug, max(qty, 1))]
    extra = str(getattr(order, "cross_sell_slug", "") or getattr(order, "secondary_product", "") or "").strip()
    if extra or bool(getattr(order, "bundle_enabled", False)):
        extra_qty = int(getattr(order, "secondary_qty", None) or 1)
        lines.append((extra or "extra", max(extra_qty, 1)))
    upsell = str(getattr(order, "upsell_slug", "") or "").strip()
    if upsell and upsell != extra:
        lines.append((upsell, 1))
    return lines


def _meta_goods(order: Any) -> str:
    return " | ".join(sku for sku, _qty in _sku_lines(order))


def _quick_goods(order: Any) -> str:
    return " | ".join(f"{sku} ({qty})" for sku, qty in _sku_lines(order))


def _cod_number(order: Any) -> int:
    try:
        return int(round(cents_to_mad(int(getattr(order, "total_cents", 0) or 0))))
    except Exception:
        return 0


def _can_open(order: Any) -> bool:
    value = getattr(order, "can_open", None)
    if value is None:
        value = getattr(order, "canOpen", None)
    return bool(value) if value is not None else False


def _qr_payload(order: Any, fallback: str) -> str:
    ticket = str(getattr(order, "meta_livraison_ticket_url", "") or "").strip()
    tracking = tracking_of(order)
    return ticket or tracking or fallback


def _qr_image(payload: str) -> ImageReader:
    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M, box_size=8, border=0)
    qr.add_data(payload or " ")
    qr.make(fit=True)
    generated: Any = qr.make_image(fill_color="black", back_color="white")
    source: Any = generated.get_image() if hasattr(generated, "get_image") else generated
    img = source.convert("RGB")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def _barcode(c: canvas.Canvas, value: str, x: float, y: float, width: float, height: float) -> None:
    try:
        bar_width = 0.95
        barcode = code128.Code128(value, barHeight=height, barWidth=bar_width, humanReadable=0)
        while barcode.width > width and bar_width > 0.32:
            bar_width -= 0.04
            barcode = code128.Code128(value, barHeight=height, barWidth=bar_width, humanReadable=0)
        barcode.drawOn(c, x + max(0, (width - barcode.width) / 2), y)
    except Exception:
        _regular, bold = _ensure_fonts()
        c.setFont(bold, 8)
        c.drawCentredString(x + width / 2, y + height / 2, value)


def _spaced(code: str) -> str:
    return " ".join(list((code or "").strip()))


def _shipment_date(order: Any) -> str:
    value = getattr(order, "meta_livraison_sent_at", None) or getattr(order, "created_at", None)
    if isinstance(value, datetime):
        try:
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(TZ).strftime("%d/%m/%Y")
        except Exception:
            return value.strftime("%d/%m/%Y")
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.astimezone(TZ).strftime("%d/%m/%Y")
        except Exception:
            pass
    return datetime.now(TZ).strftime("%d/%m/%Y")


PRODUCT_NAMES = {
    "quran": "USB القرآن",
    "taalim": "USB التعليمي",
    "music": "USB الموسيقى",
    "zit_alfasokh": "زيت الفسوخ",
    "alkhatm_alrijali": "الخاتم الرجالي",
    "almisk_alabyad": "المسك الأبيض",
    "kids": "USB تعليم الأطفال",
    "educative": "الفلاشة التعليمية الذكية",
    "extra": "مفتاح إضافي",
    "pack-royal-power": "الباك الملكي المتكامل",
    "pack-royal": "الباك الملكي المتكامل",
}


def _reference_goods(order: Any) -> str:
    custom = str(getattr(order, "custom_product_name", "") or "").strip()
    parts: list[str] = []
    for index, (slug, qty) in enumerate(_sku_lines(order)):
        name = custom if index == 0 and custom else PRODUCT_NAMES.get(slug, slug)
        parts.append(f"{name} x {qty}")
    return " + ".join(parts) or "—"


def _carrier_label(order: Any) -> str:
    carrier = normalize_carrier(getattr(order, "carrier", None))
    if carrier == "gooli":
        return "GOOLI EXPRESS"
    if carrier == CARRIER_QUICK:
        return "QUICK LIVRAISON"
    if carrier == "force_log":
        return "FORCE LOG"
    return "META LIVRAISON"


def _checkbox(c: canvas.Canvas, x: float, y: float, checked: bool) -> None:
    size = 4.2 * mm
    c.setLineWidth(1.2)
    c.rect(x, y, size, size, stroke=1, fill=0)
    if checked:
        c.setLineWidth(1.4)
        c.line(x + 0.8 * mm, y + 2 * mm, x + 1.8 * mm, y + 0.9 * mm)
        c.line(x + 1.8 * mm, y + 0.9 * mm, x + 3.5 * mm, y + 3.4 * mm)


def _draw_livmax_logo(c: canvas.Canvas, cx: float, cy: float) -> None:
    _regular, bold = _ensure_fonts()
    c.saveState()
    c.setFillColor(black)
    c.setStrokeColor(black)
    c.setLineWidth(1.4)
    # Compact delivery mark followed by the production wordmark.
    c.roundRect(cx - 13.5 * mm, cy - 3.5 * mm, 5.5 * mm, 7 * mm, 1.4 * mm, stroke=1, fill=0)
    c.line(cx - 12 * mm, cy + 1.8 * mm, cx - 9.5 * mm, cy + 1.8 * mm)
    c.line(cx - 12 * mm, cy, cx - 9.5 * mm, cy)
    c.setFont(bold, 12)
    c.drawString(cx - 7 * mm, cy - 2.2 * mm, "livmax")
    c.setFont(bold, 3.8)
    c.drawCentredString(cx, cy - 6 * mm, "LOGISTICS SOLUTIONS")
    c.restoreState()


def _fill_black(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    c.setFillColor(black)
    c.rect(x, y, w, h, stroke=0, fill=1)
    c.setFillColor(white)


def _draw_meta_logo(c: canvas.Canvas, cx: float, cy: float) -> None:
    c.setStrokeColor(black)
    c.setFillColor(black)
    c.setLineWidth(2.2)
    c.setLineCap(1)
    c.setLineJoin(1)
    path = c.beginPath()
    path.moveTo(cx - 9 * mm, cy - 2.4 * mm)
    path.curveTo(cx - 7 * mm, cy + 5.2 * mm, cx - 1.6 * mm, cy + 5.6 * mm, cx, cy + 0.6 * mm)
    path.curveTo(cx + 1.6 * mm, cy + 5.6 * mm, cx + 7 * mm, cy + 5.2 * mm, cx + 9 * mm, cy - 2.4 * mm)
    c.drawPath(path, stroke=1, fill=0)
    c.saveState()
    c.translate(cx + 7.2 * mm, cy - 0.2 * mm)
    c.rotate(-20)
    c.rect(0, -0.7 * mm, 3.6 * mm, 1.4 * mm, stroke=0, fill=1)
    c.restoreState()


def _draw_quick_mark(c: canvas.Canvas, x: float, y: float) -> None:
    size = 8.2 * mm
    top = [(x + size / 2, y + size), (x + size, y + size * 0.62), (x + size / 2, y + size * 0.28), (x, y + size * 0.62)]
    left = [(x, y + size * 0.62), (x + size / 2, y + size * 0.28), (x + size / 2, y), (x, y + size * 0.34)]
    right = [(x + size / 2, y + size * 0.28), (x + size, y + size * 0.62), (x + size, y + size * 0.34), (x + size / 2, y)]
    for color, pts in ((BLUE, top), (NAVY, left), (GREEN, right)):
        c.setFillColor(color)
        path = c.beginPath()
        path.moveTo(*pts[0])
        for pt in pts[1:]:
            path.lineTo(*pt)
        path.close()
        c.drawPath(path, fill=1, stroke=0)
    c.setFillColor(black)


def _draw_meta(c: canvas.Canvas, order: Any, tarifs: TarifIndex | None = None) -> None:
    _ensure_fonts()
    w, h = PAGE
    tracking = tracking_of(order)
    code = parcel_code(str(getattr(order, "id", "") or "ORDER"))
    hub = destination_hub(order, tarifs)
    today = datetime.now(TZ).strftime("%d/%m/%Y")
    notes = str(getattr(order, "courier_notes", "") or "").strip()
    open_label = "مسموح فتح الطلبية" if _can_open(order) else "ممنوع فتح الطلبية"
    qr_value = _qr_payload(order, code)

    inset = 0.7 * mm
    c.setStrokeColor(black)
    c.setLineWidth(1.6)
    c.rect(inset, inset, w - 2 * inset, h - 2 * inset, stroke=1, fill=0)
    left = inset
    right = w - inset
    top = h - inset

    header_h = 10.6 * mm
    header_y = top - header_h
    c.setLineWidth(1.2)
    c.line(left, header_y, right, header_y)
    _draw_meta_logo(c, w / 2 - 18 * mm, header_y + 5.2 * mm)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(w / 2 - 6 * mm, header_y + 5.6 * mm, "metalivraison")
    _draw_text(c, TAGLINE, w / 2 - 6 * mm, header_y + 2.2 * mm, 5.4, bold=True)

    sender_h = 9.6 * mm
    sender_y = header_y - sender_h
    split_x = left + 58 * mm
    c.line(left, sender_y, right, sender_y)
    c.line(split_x, sender_y, split_x, header_y)
    _draw_text(c, f"Expediteur : {META_SENDER_NAME} ({META_SENDER_CODE})", left + 1.6 * mm, header_y - 4 * mm, 6.2, bold=True)
    _draw_text(c, f"Telephone : {META_SENDER_PHONE}", left + 1.6 * mm, header_y - 7.6 * mm, 6.1, bold=True)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(split_x + 1.6 * mm, header_y - 4.4 * mm, "Départ :")
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(right - 1.6 * mm, header_y - 4.2 * mm, f"HUB {META_DEPART_HUB}")
    c.setFont("Helvetica-Bold", 6.6)
    c.drawRightString(right - 1.6 * mm, header_y - 7.6 * mm, today)

    banner_h = 6.8 * mm
    banner_y = sender_y - banner_h
    _fill_black(c, left, banner_y, right - left, banner_h)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(w / 2, banner_y + 2.1 * mm, f"HUB {hub}")
    c.setFillColor(black)

    footer_h = 4.8 * mm
    footer_y = inset
    barcode_h = 16.2 * mm
    barcode_y = footer_y + footer_h
    colis_h = 5 * mm
    colis_y = barcode_y + barcode_h
    body_top = banner_y
    body_bot = colis_y + colis_h
    c.setStrokeColor(black)
    c.setLineWidth(1.2)
    c.line(left, body_bot, right, body_bot)

    qr_col_w = 32 * mm
    qr_x = right - qr_col_w
    c.line(qr_x, body_bot, qr_x, body_top)

    fields = [
        ("Destinataire", str(getattr(order, "full_name", "") or "—")),
        ("Telephone", _phone(order, "meta")),
        ("Ville", _ville(order)),
        ("Adresse :", _address(order)),
        ("Commentaire:", notes),
        ("Marchendise", _meta_goods(order)),
    ]
    row_h = (body_top - body_bot) / len(fields)
    for i, (label, value) in enumerate(fields):
        y = body_top - (i + 1) * row_h
        if i:
            c.setLineWidth(0.7)
            c.line(left, y + row_h, qr_x, y + row_h)
        _draw_text(c, label, left + 1.5 * mm, y + row_h - 3.3 * mm, 5.4, bold=True)
        value_x = left + 22 * mm
        font = _font_for(value, True)
        lines = _wrap(value, font, 6.4, qr_x - value_x - 1.6 * mm, 2 if label.startswith("Adresse") else 1)
        cursor = y + row_h - 3.3 * mm
        for line in lines:
            _draw_text(c, line, value_x, cursor, 6.4, bold=True)
            cursor -= 2.8 * mm

    montant_h = 11 * mm
    qr_box_h = body_top - body_bot - montant_h
    qr_size = min(24 * mm, qr_box_h - 2.4 * mm)
    qr_img_x = qr_x + (qr_col_w - qr_size) / 2
    qr_img_y = body_bot + montant_h + (qr_box_h - qr_size) / 2
    c.drawImage(_qr_image(qr_value), qr_img_x, qr_img_y, qr_size, qr_size, preserveAspectRatio=True, mask="auto")
    c.setLineWidth(1.1)
    c.line(qr_x, body_bot + montant_h, right, body_bot + montant_h)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 6)
    c.drawCentredString(qr_x + qr_col_w / 2, body_bot + montant_h - 3 * mm, "MONTANT")
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(qr_x + qr_col_w / 2, body_bot + 2.4 * mm, f"{_cod_number(order)} MAD")

    c.setLineWidth(1.2)
    c.line(left, colis_y, right, colis_y)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(w / 2, colis_y + 1.5 * mm, "COLIS NORMAL")

    open_w = 9.2 * mm
    c.line(right - open_w, barcode_y, right - open_w, colis_y)
    _barcode(c, code, left + 1.4 * mm, barcode_y + 5.4 * mm, right - open_w - left - 2.8 * mm, 8.8 * mm)
    c.setFont("Helvetica-Bold", 5.6)
    c.drawCentredString((left + right - open_w) / 2, barcode_y + 1.6 * mm, code)
    c.saveState()
    c.translate(right - open_w / 2, (barcode_y + colis_y) / 2)
    c.rotate(90)
    _draw_text(c, open_label, 0, -1.6, 5.6, bold=True, align="center")
    c.restoreState()

    _fill_black(c, left, footer_y, right - left, footer_h)
    c.setFont("Helvetica-Bold", 4.4)
    c.drawCentredString(w / 2, footer_y + 1.6 * mm, DISCLAIMER)
    c.setFillColor(black)
    _ = tracking


def _draw_quick(c: canvas.Canvas, order: Any, tarifs: TarifIndex | None = None) -> None:
    _ = tarifs
    _ensure_fonts()
    w, h = PAGE
    tracking = tracking_of(order) or parcel_code(str(getattr(order, "id", "") or "ORDER"))
    qr_value = _qr_payload(order, tracking)

    inset = 0.7 * mm
    c.setStrokeColor(black)
    c.setLineWidth(1.4)
    c.rect(inset, inset, w - 2 * inset, h - 2 * inset, stroke=1, fill=0)
    left = inset
    right = w - inset
    top = h - inset

    header_h = 12 * mm
    header_y = top - header_h
    split = left + 62 * mm
    c.setLineWidth(1.1)
    c.line(left, header_y, right, header_y)
    c.line(split, header_y, split, top)
    _draw_quick_mark(c, left + 1.6 * mm, header_y + 1.8 * mm)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left + 12 * mm, header_y + 6.8 * mm, "Quick Livraison")
    c.setFillColor(GREEN)
    c.setFont("Helvetica-Bold", 6)
    c.drawString(left + 12 * mm, header_y + 3.4 * mm, "We Are Every Where")
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 6.2)
    c.drawString(split + 1.5 * mm, top - 3.2 * mm, "Zone Expedition:")
    box_y = header_y + 1.4 * mm
    _fill_black(c, split + 1.5 * mm, box_y, right - split - 3 * mm, 6.4 * mm)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString((split + right) / 2, box_y + 1.8 * mm, QUICK_EXPEDITION)
    c.setFillColor(black)

    grid_h = 29 * mm
    grid_y = header_y - grid_h
    col1 = left + 31 * mm
    col2 = left + 62 * mm
    c.line(left, grid_y, right, grid_y)
    c.line(col1, grid_y, col1, header_y)
    c.line(col2, grid_y, col2, header_y)
    c.setFont("Helvetica-Bold", 6.2)
    c.drawString(left + 1.4 * mm, header_y - 3.4 * mm, "Zone Reception:")
    qr_size = 21 * mm
    c.drawImage(
        _qr_image(qr_value),
        left + (col1 - left - qr_size) / 2,
        grid_y + 1.6 * mm,
        qr_size,
        qr_size,
        preserveAspectRatio=True,
        mask="auto",
    )
    c.setFont("Helvetica-Bold", 6.2)
    c.drawString(col1 + 1.4 * mm, header_y - 3.4 * mm, "Expediteur:")
    c.setFont("Helvetica-Bold", 7.2)
    c.drawCentredString((col1 + col2) / 2, header_y - 10 * mm, f"{QUICK_SENDER_NAME} - ({QUICK_SENDER_CODE})")
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString((col1 + col2) / 2, header_y - 15 * mm, QUICK_SENDER_PHONE)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString((col1 + col2) / 2, header_y - 21.5 * mm, "STOCK")
    c.setFont("Helvetica-Bold", 6.2)
    c.drawString(col2 + 1.4 * mm, header_y - 3.4 * mm, "Destinataire:")
    dest_x = col2 + 1.6 * mm
    dest_w = right - dest_x - 1.4 * mm
    _draw_text(c, str(getattr(order, "full_name", "") or "—"), dest_x, header_y - 8.2 * mm, 7.4, bold=True)
    _draw_text(c, _phone(order, "quick"), dest_x, header_y - 12.4 * mm, 7, bold=True)
    _draw_text(c, _ville(order), dest_x, header_y - 16.6 * mm, 7.2, bold=True)
    addr_font = _font_for(_address(order), True)
    for i, line in enumerate(_wrap(_address(order), addr_font, 6.4, dest_w, 3)):
        _draw_text(c, line, dest_x, header_y - 21 * mm - i * 3.2 * mm, 6.4, bold=True)

    flags_h = 7.2 * mm
    flags_y = grid_y - flags_h
    mid = (left + right) / 2
    c.line(left, flags_y, right, flags_y)
    c.line(mid, flags_y, mid, grid_y)
    open_text = "Autorisé à ouvrir" if _can_open(order) else "Interdit d'ouvrir"
    _draw_text(c, open_text, (left + mid) / 2, flags_y + 2.4 * mm, 8, bold=True, align="center")
    c.drawCentredString((mid + right) / 2, flags_y + 2.4 * mm, "Interdit d'essayer")

    goods_h = 16.5 * mm
    goods_y = flags_y - goods_h
    crbt_x = left + (right - left) * 0.75
    c.line(left, goods_y, right, goods_y)
    c.line(crbt_x, goods_y, crbt_x, flags_y)
    c.setFont("Helvetica-Bold", 6.2)
    c.drawString(left + 1.5 * mm, flags_y - 3.2 * mm, "Marchandise:")
    goods = _quick_goods(order)
    goods_font = _font_for(goods, True)
    for i, line in enumerate(_wrap(goods, goods_font, 6.2, crbt_x - left - 3.2 * mm, 4)):
        _draw_text(c, line, left + 1.5 * mm, flags_y - 7 * mm - i * 3 * mm, 6.2, bold=True)
    c.setFont("Helvetica-Bold", 6.4)
    c.drawCentredString((crbt_x + right) / 2, flags_y - 3.4 * mm, "Crbt:")
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString((crbt_x + right) / 2, goods_y + 4.8 * mm, f"{_cod_number(order)} DH")

    _barcode(c, tracking, left + 2 * mm, goods_y - 14.2 * mm, right - left - 4 * mm, 10.5 * mm)
    c.setFont("Courier-Bold", 7.2)
    c.drawCentredString(w / 2, inset + 2.2 * mm, _spaced(tracking))


def _draw_reference(c: canvas.Canvas, order: Any, tarifs: TarifIndex | None = None) -> None:
    _ = tarifs
    _regular_font, bold_font = _ensure_fonts()
    w, h = PAGE
    inset = 1 * mm
    left, right, bottom, top = inset, w - inset, inset, h - inset
    order_id = str(getattr(order, "id", "") or "ORDER")
    tracking = tracking_of(order) or f"CFG-{order_id.replace('-', '')[:6].upper()}"
    qr_value = _qr_payload(order, tracking)

    c.setStrokeColor(black)
    c.setFillColor(black)
    c.setLineWidth(1.3)
    c.rect(left, bottom, right - left, top - bottom, stroke=1, fill=0)

    details_bottom = top - 32.5 * mm
    flags_bottom = details_bottom - 8.5 * mm
    product_bottom = flags_bottom - 10 * mm
    crbt_bottom = product_bottom - 10 * mm
    vendor_bottom = crbt_bottom - 11 * mm
    for y in (details_bottom, flags_bottom, product_bottom, crbt_bottom, vendor_bottom):
        c.setLineWidth(1.15)
        c.line(left, y, right, y)

    # Recipient information and floating Livmax mark in one undivided box.
    label_x = left + 2 * mm
    value_x = left + 20 * mm
    details = [
        ("Nom complet", str(getattr(order, "full_name", "") or "—"), top - 4 * mm, 1, True),
        ("Téléphone", _phone(order, "quick"), top - 8.2 * mm, 1, True),
        ("Ville", str(getattr(order, "shipping_city", "") or getattr(order, "city", "") or "—"), top - 12.4 * mm, 1, True),
        ("Adresse", _address(order), top - 16.6 * mm, 2, False),
        ("Commentaire", str(getattr(order, "courier_notes", "") or "—"), top - 22.3 * mm, 2, False),
        ("Date d'envoi", _shipment_date(order), top - 28.8 * mm, 1, False),
    ]
    for label, value, baseline, max_lines, under_logo in details:
        _draw_text(c, f"{label}:", label_x, baseline, 5.5, bold=True)
        font = _font_for(value, True)
        value_w = (right - 29 * mm if under_logo else right - 2 * mm) - value_x
        lines = _wrap(value, font, 6.5, value_w, max_lines)
        for line_index, line in enumerate(lines):
            _draw_text(c, line, value_x, baseline - line_index * 2.3 * mm, 6.2, bold=True)

    _draw_livmax_logo(c, right - 13.5 * mm, top - 7.2 * mm)

    # Arabic service options.
    mid = (left + right) / 2
    box_y = flags_bottom + 2.15 * mm
    _checkbox(c, left + 5 * mm, box_y, False)
    _draw_text(c, "لا يمكنك فتح الطلبية", left + 29 * mm, flags_bottom + 3 * mm, 6.6, bold=True, align="center")
    _checkbox(c, mid + 5 * mm, box_y, False)
    _draw_text(c, "إستبدال المنتوج", mid + 28 * mm, flags_bottom + 3 * mm, 6.6, bold=True, align="center")

    # Product and COD amount.
    _draw_text(c, "Produit:", left + 2 * mm, product_bottom + 3.4 * mm, 6.5, bold=True)
    goods = _reference_goods(order)
    goods_font = _font_for(goods, True)
    goods_lines = _wrap(goods, goods_font, 6.8, right - left - 23 * mm, 2)
    goods_y = flags_bottom - 3.5 * mm
    goods_cx = left + 20 * mm + (right - left - 22 * mm) / 2
    for index, line in enumerate(goods_lines):
        _draw_text(c, line, goods_cx, goods_y - index * 2.8 * mm, 6.8, bold=True, align="center")

    c.setFont(bold_font, 11)
    c.drawCentredString((left + right) / 2, crbt_bottom + 3.2 * mm, f"CRBT: {_cod_number(order)} DH")

    # Centered production vendor line with the fixed production phone.
    c.setFont(bold_font, 6.6)
    c.drawCentredString((left + right) / 2, vendor_bottom + 6.5 * mm, f"Vendeur : <-- glow --> - {DEFAULT_VENDOR_PHONE}")
    c.setFont(bold_font, 5.2)
    c.drawCentredString((left + right) / 2, vendor_bottom + 2.4 * mm, "Nous vous remercions pour votre confiance:")

    # Barcode and QR footer.
    qr_left = left + (right - left) * 0.68
    c.setLineWidth(1.15)
    c.line(qr_left, bottom, qr_left, vendor_bottom)
    barcode_w = qr_left - left - 4 * mm
    barcode_h = 12 * mm
    _barcode(c, tracking, left + 2 * mm, bottom + 9.5 * mm, barcode_w, barcode_h)
    code_font = bold_font
    code_size = 6.8
    c.setFont(code_font, code_size)
    code = tracking
    while code_size > 4.5 and pdfmetrics.stringWidth(code, code_font, code_size) > barcode_w:
        code_size -= 0.3
        c.setFont(code_font, code_size)
    c.drawCentredString((left + qr_left) / 2, bottom + 4.1 * mm, code)

    qr_size = min(22 * mm, vendor_bottom - bottom - 4 * mm)
    qr_x = qr_left + (right - qr_left - qr_size) / 2
    qr_y = bottom + (vendor_bottom - bottom - qr_size) / 2
    c.drawImage(_qr_image(qr_value), qr_x, qr_y, qr_size, qr_size, preserveAspectRatio=True, mask="auto")


def _draw_page(c: canvas.Canvas, order: Any, tarifs: TarifIndex | None = None) -> None:
    _draw_reference(c, order, tarifs)


def render_label_pdf(orders: list[Any], tarifs: TarifIndex | None = None) -> bytes:
    if not orders:
        raise ValueError("no_labels")
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGE)
    c.setTitle("Chifaglow — Shipping Labels 100x100")
    for index, order in enumerate(orders):
        if index:
            c.showPage()
        _draw_page(c, order, tarifs)
    c.save()
    return buf.getvalue()
