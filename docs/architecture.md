# Chifaglow Architecture

Brand: **Chifaglow / شيفا جلو**  
Storefront: `https://chifaglow.com`  
API: `https://api.chifaglow.com`  
Market: Morocco, Cash on Delivery only (MAD).

This document is the system map for the Next.js storefront, FastAPI backend, PostgreSQL, CAPI, Google Sheets, and Easypanel Docker deployment.

---

## 1. High-level diagram

```
TikTok / Meta / Snap ads
        │
        ▼
┌───────────────────────────────────────────────┐
│  Next.js 15 App Router  (chifaglow.com)       │
│  RTL Arabic / Darija · mobile-first CRO       │
│  Deferred web pixels (lazy after idle)        │
│  Cart drawer → COD popup → 12s upsell         │
└────────────────────┬──────────────────────────┘
                     │ HTTPS JSON
                     ▼
┌───────────────────────────────────────────────┐
│  FastAPI  (api.chifaglow.com)                 │
│  Validate phone + city + server-side prices   │
│  Persist order → Alembic/PostgreSQL           │
│  Background: Meta/TikTok/Snap CAPI + Sheets   │
└──────────┬─────────────────────┬──────────────┘
           │                     │
           ▼                     ▼
   PostgreSQL (Easypanel)   Google Apps Script
   host: chifaglow_chifaglow    → Sheet "Orders"
```

Event `event_id` is generated in the browser (UUID v4) and reused on:

1. Facebook Pixel / TikTok Pixel / Snapchat Pixel (`eventID` / `event_id`)
2. FastAPI CAPI payloads (`event_id`)

That is the only deduplication key. See `docs/tracking_capi.md`.

---

## 2. Repositories / folders

```
/
├── docs/                          # this spec pack
├── google_sheets/
│   ├── code.js                    # Apps Script (deploy as Web App)
│   ├── google_sheet_script.js     # same script, alias name
│   └── orders_template.csv
├── backend/                       # FastAPI + SQLModel + Alembic
├── frontend/                      # Next.js App Router
├── docker-compose.yml
└── env.example
```

---

## 3. Database schema (PostgreSQL)

SQLModel tables. Money is stored as integer **centimes** (199.00 MAD → `19900`) to avoid float drift.

### `products`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| slug | VARCHAR unique | `quran`, `kids`, `music` |
| name_ar | VARCHAR | USB القرآن الكريم / … |
| name_en | VARCHAR | |
| tagline_ar | VARCHAR | |
| description_ar | TEXT | |
| accent | VARCHAR | `gold`, `emerald`, `royal` |
| is_active | BOOLEAN | default true |
| created_at | TIMESTAMPTZ | |

### `orders`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | public order id |
| full_name | VARCHAR | |
| phone | VARCHAR | E.164 `+2126…` |
| phone_national | VARCHAR | `06…` display form |
| city | VARCHAR | must match catalog |
| product_slug | VARCHAR | primary USB |
| tier_qty | INTEGER | 1, 2 or 3 |
| tier_price_cents | INTEGER | 19900 / 27900 / 34900 |
| cross_sell_slug | VARCHAR nullable | extra USB @ 199 MAD |
| cross_sell_price_cents | INTEGER | 0 or 19900 |
| upsell_slug | VARCHAR nullable | extra USB @ 99 MAD |
| upsell_price_cents | INTEGER | 0 or 9900 |
| subtotal_cents | INTEGER | before upsell |
| total_cents | INTEGER | after upsell |
| currency | VARCHAR | `MAD` |
| status | VARCHAR | `pending`, `upsell_accepted`, `confirmed` |
| payment_method | VARCHAR | always `COD` |
| event_id | VARCHAR unique | pixel ↔ CAPI |
| fbp / fbc / ttclid / sccid | VARCHAR | click ids |
| client_ip | VARCHAR | |
| user_agent | TEXT | |
| landing_url | TEXT | |
| source | VARCHAR | `website` |
| created_at / updated_at | TIMESTAMPTZ | |

### `order_items`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| order_id | UUID FK | |
| product_slug | VARCHAR | |
| role | VARCHAR | `primary`, `cross_sell`, `upsell` |
| quantity | INTEGER | |
| unit_price_cents | INTEGER | |
| line_total_cents | INTEGER | |

### `tracking_events`

Audit log of CAPI attempts (success/failure, platform, event name, `event_id`).

---

## 4. Canonical pricing (server is source of truth)

Never trust client-sent MAD amounts. The API only accepts slugs + tier qty.

| Selection | Qty | Price |
|---|---|---|
| Standard tier | 1 | 199 MAD |
| Standard tier | 2 | 279 MAD |
| Standard tier | 3 | 349 MAD |
| Cross-sell (cart drawer) | 1 other USB | 199 MAD |
| Post-purchase upsell | 1 other USB | **99 MAD** (only discount in the funnel) |

---

## 5. FastAPI layout

```
backend/
├── Dockerfile
├── requirements.txt
├── alembic.ini
├── alembic/env.py
├── alembic/versions/0001_initial.py
└── app/
    ├── main.py              # lifespan: migrate + seed
    ├── config.py
    ├── db.py
    ├── seed.py
    ├── api/
    │   ├── health.py
    │   ├── products.py
    │   ├── cities.py
    │   ├── orders.py
    │   └── tracking.py
    ├── models/
    ├── schemas/
    └── services/
        ├── cities.py
        ├── phone.py
        ├── hashing.py
        ├── pricing.py
        ├── capi.py
        └── sheets.py
```

Startup command inside the container:

```text
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

SQLAlchemy URL: `postgres://` is rewritten to `postgresql+psycopg2://` in `config.py`.

---

## 6. Next.js folder structure

```
frontend/
├── Dockerfile
├── next.config.ts            # output: "standalone"
├── tailwind.config.ts        # royal / emerald / gold tokens
└── src/
    ├── app/
    │   ├── layout.tsx        # dir=rtl lang=ar
    │   ├── page.tsx          # home
    │   ├── products/[slug]/page.tsx
    │   └── thank-you/page.tsx
    ├── components/
    │   ├── layout/           # TopBar, Header, Footer
    │   ├── cart/CartDrawer.tsx
    │   ├── checkout/         # popup + city search + phone
    │   ├── upsell/UpsellPopup.tsx
    │   ├── product/          # pricing, scarcity, reviews, sticky CTA
    │   ├── home/
    │   └── tracking/PixelLoader.tsx
    └── lib/
        ├── products.ts
        ├── cities.ts
        ├── phone.ts
        ├── tracking.ts
        ├── api.ts
        └── cart-context.tsx
```

Public env vars are baked at **image build time** (`ARG` / `ENV` in the frontend Dockerfile). Rebuild the frontend after changing pixel IDs.

---

## 7. Conversion pipeline (runtime)

1. **Landing** — product LP or home. `PageView` + `ViewContent` after pixels hydrate.
2. **Tier select** — 1 / 2 / 3 pieces. Default highlight: 2 pieces (AOV).
3. **CTA** `أطلب الآن - الدفع عند الاستلام` → add to cart + open drawer + `AddToCart`.
4. **Cart drawer** — selected tier + cross-sell of a different USB at 199 MAD.
5. **Drawer CTA** → checkout popup + `InitiateCheckout`.
6. **COD popup** — name, Moroccan phone, searchable city. Submit `POST /api/orders`.
7. **CAPI + Sheets** run as FastAPI `BackgroundTasks` so the HTTP response stays fast.
8. **Upsell popup** (12s countdown) — extra USB at 99 MAD. `POST /api/orders/{id}/upsell`.
9. **Thank-you** — confirmation, 24–48h delivery copy, order summary.

---

## 8. Docker / Easypanel

| Service | Image | Port | Notes |
|---|---|---|---|
| `frontend` | Next.js standalone | 3000 | Map domain `chifaglow.com` |
| `backend` | Uvicorn | 8000 | Map domain `api.chifaglow.com` |
| Postgres | Easypanel managed | 5432 | host `chifaglow_chifaglow` — **do not** start compose `db` in production |

Local-only database:

```bash
docker compose --profile local up -d db
```

Health: `GET https://api.chifaglow.com/health`.

---

## 9. Security notes

- Prices, phone, and city are validated on the server.
- CAPI tokens never go to the browser — only `NEXT_PUBLIC_*_PIXEL_ID`.
- PII hashed with SHA-256 before CAPI (`docs/tracking_capi.md`).
- Google Sheet receives **unhashed** name/phone/city so ops can call the customer. Treat the Sheet as confidential.
