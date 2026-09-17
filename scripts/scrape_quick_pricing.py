#!/usr/bin/env python3
"""Scrape Quick Livraison city delivery prices into a JSON file.

The public page at https://quicklivraison.ma/pricing renders a DataTables
grid (25 rows/page). Rows come from GET /getDeliveryDataPricing. This script
loops page=1,2,... on both the HTML table and the JSON endpoint until a page
returns no new rows, then writes the merged result.
"""

from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://quicklivraison.ma"
PRICING_URL = f"{BASE}/pricing"
API_URL = f"{BASE}/getDeliveryDataPricing"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": PRICING_URL,
}
MAX_PAGES = 200
CTX = ssl.create_default_context()

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "app" / "data" / "quick_pricing.json"
PRICE_RE = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*(?:DH|MAD)?", re.I)


class DeliveryTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_tbody = False
        self.in_row = False
        self.in_cell = False
        self.skip_header = False
        self.current: list[str] = []
        self.cell = []
        self.rows: list[list[str]] = []
        self.table_id = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: (v or "") for k, v in attrs}
        if tag == "table":
            self.table_id = attr.get("id", "")
            if self.table_id == "deliveryTable" or not self.in_table:
                self.in_table = True
        elif self.in_table and tag == "tbody":
            self.in_tbody = True
        elif self.in_table and tag == "tr":
            self.in_row = True
            self.current = []
        elif self.in_row and tag == "td":
            self.in_cell = True
            self.cell = []
        elif self.in_row and tag == "th":
            self.skip_header = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.in_cell:
            self.current.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if not self.skip_header and len(self.current) >= 3:
                self.rows.append(self.current[:3])
            self.in_row = False
            self.skip_header = False
            self.current = []
        elif tag == "tbody":
            self.in_tbody = False
        elif tag == "table":
            self.in_table = False

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell.append(data)


def fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=60, context=CTX) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.status, resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body


def parse_price(raw: str) -> float | None:
    text = (raw or "").strip()
    if not text or text == "-":
        return None
    match = PRICE_RE.search(text.replace("\u00a0", " "))
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def normalize_row(city: str, delay: str, price_raw: str | float | int) -> dict:
    price = parse_price(str(price_raw)) if not isinstance(price_raw, (int, float)) else float(price_raw)
    return {
        "city": (city or "").strip(),
        "delivery_price_mad": price,
        "delivery_delay": (delay or "").strip() or None,
    }


def row_key(item: dict) -> tuple[str, float | None, str | None]:
    return (
        item["city"].casefold(),
        item["delivery_price_mad"],
        item["delivery_delay"],
    )


def scrape_html_pages() -> list[dict]:
    collected: list[dict] = []
    seen: set[tuple] = set()
    for page in range(1, MAX_PAGES + 1):
        url = f"{PRICING_URL}?page={page}"
        status, body = fetch(url)
        if status >= 400 or not body:
            print(f"[html] page={page} status={status} stop", flush=True)
            break
        parser = DeliveryTableParser()
        parser.feed(body)
        page_rows = [normalize_row(*cells) for cells in parser.rows if cells[0].strip()]
        new_rows = [row for row in page_rows if row_key(row) not in seen]
        print(
            f"[html] page={page} rows={len(page_rows)} new={len(new_rows)}",
            flush=True,
        )
        if not page_rows:
            break
        if not new_rows:
            # Same payload on every page (client-side DataTables). Stop looping.
            break
        for row in new_rows:
            seen.add(row_key(row))
            collected.append(row)
    return collected


def delay_index(city_delivery_data: list[dict]) -> dict[str, str]:
    index: dict[str, str] = {}
    for item in city_delivery_data:
        name = str(item.get("configs_val") or item.get("english") or "").strip()
        delay = item.get("DeliveryDelay")
        if name and delay:
            index[name.casefold()] = str(delay).strip()
    return index


def parse_api_payload(payload: dict) -> list[dict]:
    original = ((payload.get("tarifsData") or {}).get("original") or {})
    fees = original.get("fees_by_city") or []
    delays = delay_index(payload.get("cityDeliveryData") or [])
    rows: list[dict] = []
    for item in fees:
        city_list = item.get("city") or []
        city_name = ""
        if city_list and isinstance(city_list[0], dict):
            city_name = str(city_list[0].get("configs_val") or "").strip()
        if not city_name:
            continue
        delay = delays.get(city_name.casefold())
        rows.append(normalize_row(city_name, delay or "-", item.get("fees") or "-"))
        if rows[-1]["delivery_delay"] == "-":
            rows[-1]["delivery_delay"] = delay
    return rows


def scrape_api_pages() -> list[dict]:
    collected: list[dict] = []
    seen: set[tuple] = set()
    for page in range(1, MAX_PAGES + 1):
        url = f"{API_URL}?page={page}"
        status, body = fetch(url)
        if status >= 400 or not body:
            print(f"[api] page={page} status={status} stop", flush=True)
            break
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            print(f"[api] page={page} not json stop", flush=True)
            break
        page_rows = parse_api_payload(payload)
        new_rows = [row for row in page_rows if row_key(row) not in seen]
        print(
            f"[api] page={page} rows={len(page_rows)} new={len(new_rows)}",
            flush=True,
        )
        if not page_rows:
            break
        if not new_rows:
            break
        for row in new_rows:
            seen.add(row_key(row))
            collected.append(row)
    return collected


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    html_rows = scrape_html_pages()
    api_rows = scrape_api_pages()

    # Prefer the API payload: it is the table's real data source and includes
    # every city, not only the 25 rows DataTables renders into the first HTML.
    rows = api_rows or html_rows
    rows.sort(key=lambda r: ((r["delivery_price_mad"] is None), r["delivery_price_mad"] or 0, r["city"].casefold()))

    payload = {
        "source": PRICING_URL,
        "api": API_URL,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
        "cities": rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved {len(rows)} cities -> {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
