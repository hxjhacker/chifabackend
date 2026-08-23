from fastapi import APIRouter

from app.services.cities import CITIES

router = APIRouter(prefix="/api")


@router.get("/cities")
def list_cities():
    return {"cities": CITIES}
