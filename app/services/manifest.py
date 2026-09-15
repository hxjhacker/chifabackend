from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from app.services.pricing import cents_to_mad

STORE_NAME = "شيفا جلو"
STORE_NAME_LATIN = "Chifa Glow"


def _order_ref(order_id: str) -> str:
    compact = str(order_id or "").replace("-", "")[:6].upper()
    return f"#CFG-{compact}" if compact else "—"


def _phone(order: Any) -> str:
    return str(getattr(order, "phone_national", "") or getattr(order, "phone", "") or "").strip() or "—"


def _city(order: Any) -> str:
    shipping = str(getattr(order, "shipping_city", "") or "").strip()
    raw = str(getattr(order, "city", "") or "").strip()
    if shipping and raw and shipping.casefold() != raw.casefold():
        return f"{raw} — {shipping}"
    return shipping or raw or "—"


def _tracking(order: Any) -> str:
    from app.services.carriers import normalize_carrier
    from app.services.carriers.quick import is_dummy_parcel_code, quick_client_code

    code = str(getattr(order, "meta_livraison_code", "") or "").strip()
    if normalize_carrier(getattr(order, "carrier", None)) == "quick_livraison" and is_dummy_parcel_code(code):
        code = quick_client_code(order) or code
    return code or "—"


def _cod(order: Any) -> float:
    try:
        return float(cents_to_mad(int(getattr(order, "total_cents", 0) or 0)))
    except (TypeError, ValueError):
        return 0.0


def render_manifest_html(orders: list[Any], *, generated_at: datetime | None = None) -> str:
    stamp = generated_at
    if stamp is None:
        try:
            stamp = datetime.now(ZoneInfo("Africa/Casablanca"))
        except Exception:
            stamp = datetime.now()
    date_label = stamp.strftime("%Y-%m-%d %H:%M")
    rows = []
    total_cod = 0.0
    for index, order in enumerate(orders, start=1):
        amount = _cod(order)
        total_cod += amount
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{escape(_order_ref(str(getattr(order, 'id', ''))))}</td>"
            f"<td>{escape(str(getattr(order, 'full_name', '') or '—'))}</td>"
            f"<td dir='ltr'>{escape(_phone(order))}</td>"
            f"<td>{escape(_city(order))}</td>"
            f"<td dir='ltr' class='tracking'>{escape(_tracking(order))}</td>"
            f"<td dir='ltr'>{amount:.2f}</td>"
            "</tr>"
        )
    body = "\n".join(rows) if rows else "<tr><td colspan='7' class='empty'>لا توجد طرود في هذه الورقة.</td></tr>"
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8" />
  <title>ورقة التسليم — {escape(STORE_NAME)}</title>
  <style>
    @page {{ size: A4; margin: 14mm; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: #0b1f3a;
      font-family: "Segoe UI", Tahoma, Arial, sans-serif;
      background: #fff;
    }}
    .sheet {{ max-width: 210mm; margin: 0 auto; padding: 8mm 4mm; }}
    .head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      border-bottom: 3px solid #d4af37;
      padding-bottom: 12px;
      margin-bottom: 16px;
    }}
    h1 {{ margin: 0; font-size: 22px; }}
    .brand {{ color: #d4af37; font-size: 13px; font-weight: 800; letter-spacing: .08em; }}
    .meta {{ text-align: left; font-size: 13px; line-height: 1.6; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th, td {{ border: 1px solid #d6c896; padding: 7px 8px; vertical-align: middle; }}
    th {{ background: #0b1f3a; color: #faf8f5; }}
    tbody tr:nth-child(even) {{ background: #faf8f5; }}
    .tracking {{ font-family: ui-monospace, Consolas, monospace; font-weight: 700; }}
    .empty {{ text-align: center; color: #667; padding: 24px; }}
    .summary {{
      margin-top: 16px;
      display: flex;
      gap: 12px;
    }}
    .card {{
      flex: 1;
      border: 1px solid #d4af37;
      border-radius: 10px;
      padding: 12px 14px;
      background: #fffdf6;
    }}
    .card b {{ display: block; font-size: 20px; margin-top: 4px; }}
    .signs {{
      margin-top: 28px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }}
    .sign {{
      min-height: 110px;
      border: 1px dashed #0b1f3a;
      border-radius: 10px;
      padding: 12px;
    }}
    .sign span {{ font-size: 12px; color: #556; }}
    .actions {{ margin: 16px 0 8px; text-align: left; }}
    .actions button {{
      border: 0;
      background: #0b1f3a;
      color: #d4af37;
      font-weight: 800;
      padding: 8px 14px;
      border-radius: 8px;
      cursor: pointer;
    }}
    @media print {{
      .actions {{ display: none; }}
      .sheet {{ padding: 0; }}
    }}
  </style>
</head>
<body>
  <div class="sheet">
    <div class="actions"><button type="button" onclick="window.print()">طباعة ورقة التسليم</button></div>
    <div class="head">
      <div>
        <div class="brand">{escape(STORE_NAME_LATIN)}</div>
        <h1>ورقة التسليم / Bon de Ramassage</h1>
        <div>{escape(STORE_NAME)}</div>
      </div>
      <div class="meta">
        <div>التاريخ: {escape(date_label)}</div>
        <div>عدد الطرود: {len(orders)}</div>
      </div>
    </div>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>المرجع</th>
          <th>الزبون</th>
          <th>الهاتف</th>
          <th>المدينة</th>
          <th>التتبع</th>
          <th>المبلغ (DH)</th>
        </tr>
      </thead>
      <tbody>
        {body}
      </tbody>
    </table>
    <div class="summary">
      <div class="card">إجمالي الطرود<b>{len(orders)}</b></div>
      <div class="card">إجمالي التحصيل COD<b>{total_cod:.2f} DH</b></div>
    </div>
    <div class="signs">
      <div class="sign"><strong>إمضاء التاجر</strong><br /><span>الاسم والتوقيع</span></div>
      <div class="sign"><strong>إمضاء السائق / Livreur</strong><br /><span>الاسم والتوقيع</span></div>
    </div>
  </div>
</body>
</html>
"""
