from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI

router = APIRouter()


@router.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def root_health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "Nyan Wallet API",
        "status": "ready",
    }


def register_root_health(app: FastAPI) -> None:
    app.include_router(router)
