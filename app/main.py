from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from app.api.cities import router as cities_router
from app.api.health import router as health_router
from app.api.orders import router as orders_router
from app.api.products import router as products_router
from app.api.tracking import router as tracking_router
from app.config import settings
from app.db import engine
from app.seed import seed_products


@asynccontextmanager
async def lifespan(_: FastAPI):
    with Session(engine) as session:
        seed_products(session)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(products_router)
app.include_router(cities_router)
app.include_router(orders_router)
app.include_router(tracking_router)
