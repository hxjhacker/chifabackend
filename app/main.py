from contextlib import asynccontextmanager
import json
import logging
import threading
import traceback

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlmodel import SQLModel, Session

from app.api.cities import router as cities_router
from app.api.health import router as health_router
from app.api.orders import router as orders_router
from app.api.products import router as products_router
from app.api.tracking import router as tracking_router
from app.routers.admin import router as admin_router
from app.routers.admin_products import router as admin_products_router
from app.config import settings
from app.db import engine, ensure_order_columns
from app.models import CityTarif, Order, OrderItem, Product, TrackingEvent, PageView, PushSubscription  # noqa: F401
from app.seed import seed_products

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("chifaglow")


@asynccontextmanager
async def lifespan(_: FastAPI):
    SQLModel.metadata.create_all(engine)
    ensure_order_columns()
    with Session(engine) as session:
        seed_products(session)
    scheduler = BackgroundScheduler()
    try:
        from app.services.tracking_sync import run_scheduled_tracking_sync

        scheduler.add_job(
            run_scheduled_tracking_sync,
            "interval",
            hours=2,
            id="meta_tracking_sync",
            replace_existing=True,
            max_instances=1,
        )
        from app.services.city_tarifs import run_scheduled_city_tarif_sync

        scheduler.add_job(
            run_scheduled_city_tarif_sync,
            "interval",
            hours=24,
            id="meta_city_tarifs",
            replace_existing=True,
            max_instances=1,
            kwargs={"force": True},
        )
        scheduler.start()
        threading.Thread(target=lambda: run_scheduled_city_tarif_sync(False), daemon=True, name="city-tarifs-boot").start()
        print("[META_TRACKING_SYNC] scheduler started (every 2 hours)", flush=True)
        print("[CITY_TARIFS] scheduler started (boot if empty, then every 24 hours)", flush=True)
    except Exception:
        traceback.print_exc()
    yield
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass


def _error_payload(exc: BaseException, path: str | None = None) -> dict:
    return {
        "error": str(exc),
        "type": type(exc).__name__,
        "path": path,
        "trace": traceback.format_exc().splitlines()[-8:],
    }


class TraceASGIMiddleware:
    """Raw ASGI catch-all. BaseHTTPMiddleware breaks /docs streaming and can 500 every route."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def send_wrapper(message):
            nonlocal started
            if message.get("type") == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            traceback.print_exc()
            path = scope.get("path")
            log.exception("UNHANDLED %s %s: %r", scope.get("method"), path, exc)
            print("ASGI EXCEPTION:", type(exc).__name__, repr(exc), "path=", path, flush=True)
            if started:
                return
            body = json.dumps(_error_payload(exc, path), ensure_ascii=False).encode("utf-8", "replace")
            await send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})


app = FastAPI(title=settings.app_name, lifespan=lifespan)
print("[BOOT] exception logging enabled", flush=True)


@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    log.exception("UNHANDLED %s %s: %r", request.method, request.url.path, exc)
    try:
        return JSONResponse(
            status_code=500,
            content={
                "error": str(exc),
                "trace": traceback.format_exc().splitlines()[-3:],
            },
        )
    except Exception:
        traceback.print_exc()
        return PlainTextResponse(f"Internal Server Error: {type(exc).__name__}: {exc}", status_code=500)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_origin_regex=r"https://([a-z0-9-]+\.)?chifaglow\.com|http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TraceASGIMiddleware)

@app.get("/")
def root():
    return {"ok": True, "service": settings.app_name}


app.include_router(health_router)
app.include_router(products_router)
app.include_router(cities_router)
app.include_router(orders_router)
app.include_router(tracking_router)
app.include_router(admin_router)
app.include_router(admin_products_router)
