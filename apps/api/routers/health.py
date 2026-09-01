from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app_env: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    from config.settings import get_settings

    return HealthResponse(status="ok", app_env=get_settings().app_env)
