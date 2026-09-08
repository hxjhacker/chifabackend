from contextlib import asynccontextmanager
import threading
import traceback

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import SQLModel, Session
from starlette.middleware.base import BaseHTTPMiddleware

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


class Json500Middleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            traceback.print_exc()
            print("MIDDLEWARE EXCEPTION:", type(exc).__name__, repr(exc), "path=", request.url.path)
            return JSONResponse(
                status_code=500,
                content={"error": str(exc), "traceback": traceback.format_exc()},
            )


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(Json500Middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_origin_regex=r"https://([a-z0-9-]+\.)?chifaglow\.com|http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(products_router)
app.include_router(cities_router)
app.include_router(orders_router)
app.include_router(tracking_router)
app.include_router(admin_router)
app.include_router(admin_products_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "traceback": traceback.format_exc()},
    )
