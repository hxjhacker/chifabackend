# Chifaglow API

FastAPI backend for **Chifaglow / شيفا جلو** — COD orders, PostgreSQL, Google Sheets webhook, and Meta / TikTok / Snapchat CAPI.

- API: `https://api.chifaglow.com`
- Health: `GET /health`

## Local setup

```bash
python -m venv .venv
.venv/Scripts/activate   # Windows
# source .venv/bin/activate  # macOS / Linux
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API: http://localhost:8000/health

## Docker

```bash
docker build -t chifaglow-api .
docker run -p 8000:8000 --env-file .env chifaglow-api
```

Container CMD runs `alembic upgrade head` then Uvicorn on port 8000.

## Docs

- `docs/backend_specs.md` — endpoints, pricing, validation
- `docs/architecture.md` — system map
- `docs/tracking_capi.md` — CAPI + `event_id` deduplication
