"""Healthcheck endpoints."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "siteiq-api", "version": "0.1.0"}