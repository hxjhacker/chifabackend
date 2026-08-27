# Backend Specs — FastAPI

Service: **Chifaglow API** at `https://api.chifaglow.com`  
Stack: FastAPI, SQLModel, Alembic, PostgreSQL, httpx, Pydantic Settings.

---

## 1. Runtime

- Gunicorn is not required; **Uvicorn** is enough behind Easypanel’s proxy.
- Container CMD: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Lifespan also **seeds** the three USB products if missing.
- CORS: `CORS_ORIGINS` (comma-separated). Credentials allowed for cookie-less JSON.

`DATABASE_URL` example (Easypanel):

```text
postgres://database:database@chifaglow_database:5432/database?sslmode=disable
```

Normalized internally to `postgresql+psycopg2://…`.

---

## 2. Endpoints

### `GET /health`

```json
{ "ok": true, "service": "chifaglow-api" }
```

### `GET /api/products`

Active catalog with Arabic names and accents.

### `GET /api/products/{slug}`

404 if unknown.

### `GET /api/cities`

```json
{ "cities": [ { "ar": "الدار البيضاء", "fr": "Casablanca", "aliases": ["casa"] } ] }
```

### `POST /api/orders`

Creates a COD order. **Server computes money.**

Request:

```json
{
  "full_name": "فاطمة الزهراء بناني",
  "phone": "0612345678",
  "city": "مراكش",
  "product_slug": "quran",
  "tier_qty": 2,
  "cross_sell_slug": "kids",
  "event_id": "4d6f0c2a-…",
  "fbp": "fb.1.…",
  "fbc": "fb.1.…",
  "ttclid": null,
  "sccid": null,
  "landing_url": "https://chifaglow.com/products/quran"
}
```

`client_ip`: `X-Forwarded-For` first hop, else `request.client.host`.  
`user_agent`: `User-Agent` header.

Validation:

- `full_name` 3–80 chars
- phone via `services/phone.py` (05/06/07/+212)
- `city` must match catalog (`ar` or `fr`, case-insensitive)
- `tier_qty` ∈ {1,2,3}
- `cross_sell_slug` ≠ `product_slug` if present
- `event_id` required (UUID string)

Response `201`:

```json
{
  "order_id": "…",
  "status": "pending",
  "subtotal_cents": 47800,
  "total_cents": 47800,
  "currency": "MAD",
  "upsell_offer": { "price_cents": 9900, "candidates": ["music"] }
}
```

Background tasks after commit:

1. Meta / TikTok / Snap **Purchase** CAPI (`event_id`)
2. Google Sheets webhook (unhashed ops payload)

### `POST /api/orders/{order_id}/upsell`

```json
{ "product_slug": "music", "event_id": "…" }
```

Rules: order exists; no upsell yet; slug ≠ primary and ≠ cross-sell; price **always 99 MAD**.

Fires a second Purchase (or `AddToCart`+`Purchase`) with the new `event_id`, then patches the Sheet row via a second POST (`status: upsell_accepted`, same `order_id`).

### `GET /api/orders/{order_id}`

Public confirmation payload (no IP, no click ids): name, city, national phone, items, totals, status.

### `POST /api/tracking/events`

For browser events that need CAPI (ViewContent, AddToCart, InitiateCheckout). Same hashing + `event_id` as Purchase.

```json
{
  "event_name": "AddToCart",
  "event_id": "…",
  "event_source_url": "https://chifaglow.com/products/quran",
  "value": 279,
  "currency": "MAD",
  "content_ids": ["quran"],
  "phone": null,
  "city": null,
  "email": null,
  "fbp": "…",
  "fbc": "…"
}
```

Phone/email/city are optional here (often unknown until checkout). IP + UA still sent.

---

## 3. Models (SQLModel)

See `docs/architecture.md` for columns. Relationships: `Order.items: list[OrderItem]`.

Status enum: `pending` → `upsell_accepted` (if they take 99 DH) → treated as `confirmed` for ops (COD still unpaid until courier).

---

## 4. Pricing module

```python
TIER_PRICE_CENTS = {1: 19900, 2: 27900, 3: 34900}
CROSS_SELL_CENTS = 19900
UPSELL_CENTS = 9900
```

`subtotal = tier + (cross_sell or 0)`  
`total = subtotal + (upsell or 0)`

---

## 5. Google Sheets payload

`POST GOOGLE_SHEETS_WEBHOOK_URL` JSON keys **exactly** matching `google_sheets/orders_template.csv`:

`order_id, created_at, full_name, phone, city, product_slug, product_name, tier_qty, tier_price, cross_sell_slug, cross_sell_price, upsell_slug, upsell_price, subtotal, total, currency, status, payment_method, event_id, landing_url, source, items_json`

`phone` in the Sheet is E.164 (`+212…`) so agents can tap-to-call from mobile.

Timeout: 8s. Failures are logged; they must **not** fail the customer order.

---

## 6. CAPI execution

`services/capi.py` sends in parallel (`httpx.AsyncClient`) to:

| Platform | Endpoint |
|---|---|
| Meta | `POST https://graph.facebook.com/v21.0/{PIXEL_ID}/events` |
| TikTok | `POST https://business-api.tiktok.com/open_api/v1.3/event/track/` |
| Snapchat | `POST https://tr.snapchat.com/v3/{PIXEL_ID}/events?access_token=` |

Empty env tokens → skip that platform (dev-safe).

User params hashed: `docs/tracking_capi.md`.

---

## 7. Alembic

- `alembic/env.py` imports all SQLModel metadata.
- Revision `0001_initial` creates `products`, `orders`, `order_items`, `tracking_events`.
- On every container start: `alembic upgrade head`.

---

## 8. Dockerfile

Python 3.12-slim, `libpq` via `psycopg2-binary`, non-root user `app`, expose 8000.
