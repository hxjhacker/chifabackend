FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ADMIN_USERNAME=manager@chifa.com \
    ADMIN_PASSWORD=adminpro@ \
    ADMIN_JWT_SECRET=204a308d75e24d90b8e47391e1cc9d33b2b08cce2dcd4482a2276542bd346504 \
    ADMIN_JWT_HOURS=12

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head || true; uvicorn app.main:app --host 0.0.0.0 --port 8000"]
