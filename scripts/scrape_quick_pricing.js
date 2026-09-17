#!/usr/bin/env node
/**
 * Scrape Quick Livraison city delivery prices into a JSON file.
 *
 * The public page at https://quicklivraison.ma/pricing renders a DataTables
 * grid (25 rows/page). Rows come from GET /getDeliveryDataPricing. This script
 * loops page=1,2,... on both the HTML table and the JSON endpoint until a page
 * returns no new rows, then writes the merged result.
 */

const fs = require("fs");
const path = require("path");

const BASE = "https://quicklivraison.ma";
const PRICING_URL = `${BASE}/pricing`;
const API_URL = `${BASE}/getDeliveryDataPricing`;
const MAX_PAGES = 200;
const DEFAULT_OUT = path.join(__dirname, "..", "app", "data", "quick_pricing.json");
const PRICE_RE = /(-?\d+(?:[.,]\d+)?)\s*(?:DH|MAD)?/i;
const HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  Accept: "application/json, text/html;q=0.9,*/*;q=0.8",
  "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
  Referer: PRICING_URL,
};

function parsePrice(raw) {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  const text = String(raw || "").replace(/\u00a0/g, " ").trim();
  if (!text || text === "-") return null;
  const match = text.match(PRICE_RE);
  if (!match) return null;
  return Number.parseFloat(match[1].replace(",", "."));
}

function normalizeRow(city, delay, priceRaw) {
  const parsedDelay = String(delay || "").trim();
  return {
    city: String(city || "").trim(),
    delivery_price_mad: parsePrice(priceRaw),
    delivery_delay: parsedDelay && parsedDelay !== "-" ? parsedDelay : null,
  };
}

function rowKey(item) {
  return `${item.city.toLowerCase()}|${item.delivery_price_mad}|${item.delivery_delay}`;
}

function parseTableRows(html) {
  const tableMatch = html.match(
    /<table[^>]*id=["']deliveryTable["'][^>]*>([\s\S]*?)<\/table>/i
  );
  const chunk = tableMatch ? tableMatch[1] : html;
  const bodyMatch = chunk.match(/<tbody[^>]*>([\s\S]*?)<\/tbody>/i);
  const body = bodyMatch ? bodyMatch[1] : chunk;
  const rows = [];
  const trRe = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
  let tr;
  while ((tr = trRe.exec(body))) {
    const cells = [...tr[1].matchAll(/<td[^>]*>([\s\S]*?)<\/td>/gi)].map((m) =>
      m[1]
        .replace(/<[^>]+>/g, " ")
        .replace(/&nbsp;/gi, " ")
        .replace(/&amp;/gi, "&")
        .replace(/\s+/g, " ")
        .trim()
    );
    if (cells.length >= 3 && cells[0]) {
      rows.push(normalizeRow(cells[0], cells[1], cells[2]));
    }
  }
  return rows;
}

async function fetchText(url) {
  const res = await fetch(url, { headers: HEADERS, redirect: "follow" });
  const body = await res.text();
  return { status: res.status, body };
}

function delayIndex(cityDeliveryData) {
  const index = new Map();
  for (const item of cityDeliveryData || []) {
    const name = String(item.configs_val || item.english || "").trim();
    const delay = item.DeliveryDelay;
    if (name && delay) index.set(name.toLowerCase(), String(delay).trim());
  }
  return index;
}

function parseApiPayload(payload) {
  const fees = payload?.tarifsData?.original?.fees_by_city || [];
  const delays = delayIndex(payload?.cityDeliveryData);
  const rows = [];
  for (const item of fees) {
    const cityName = String(item?.city?.[0]?.configs_val || "").trim();
    if (!cityName) continue;
    const delay = delays.get(cityName.toLowerCase()) || null;
    rows.push(normalizeRow(cityName, delay, item.fees));
  }
  return rows;
}

async function scrapePaged(kind, makeUrl, parseBody) {
  const collected = [];
  const seen = new Set();
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const url = makeUrl(page);
    let status;
    let body;
    try {
      ({ status, body } = await fetchText(url));
    } catch (err) {
      console.log(`[${kind}] page=${page} error=${err.message} stop`);
      break;
    }
    if (status >= 400 || !body) {
      console.log(`[${kind}] page=${page} status=${status} stop`);
      break;
    }
    const pageRows = parseBody(body);
    const newRows = pageRows.filter((row) => !seen.has(rowKey(row)));
    console.log(`[${kind}] page=${page} rows=${pageRows.length} new=${newRows.length}`);
    if (!pageRows.length) break;
    if (!newRows.length) break;
    for (const row of newRows) {
      seen.add(rowKey(row));
      collected.push(row);
    }
  }
  return collected;
}

async function main() {
  const outPath = path.resolve(process.argv[2] || DEFAULT_OUT);
  const htmlRows = await scrapePaged(
    "html",
    (page) => `${PRICING_URL}?page=${page}`,
    parseTableRows
  );
  const apiRows = await scrapePaged(
    "api",
    (page) => `${API_URL}?page=${page}`,
    (body) => {
      try {
        return parseApiPayload(JSON.parse(body));
      } catch {
        return [];
      }
    }
  );

  const rows = (apiRows.length ? apiRows : htmlRows).slice().sort((a, b) => {
    const pa = a.delivery_price_mad;
    const pb = b.delivery_price_mad;
    if (pa == null && pb == null) return a.city.localeCompare(b.city);
    if (pa == null) return 1;
    if (pb == null) return -1;
    if (pa !== pb) return pa - pb;
    return a.city.localeCompare(b.city, "fr", { sensitivity: "base" });
  });

  const payload = {
    source: PRICING_URL,
    api: API_URL,
    scraped_at: new Date().toISOString(),
    count: rows.length,
    cities: rows,
  };

  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  console.log(`saved ${rows.length} cities -> ${outPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
