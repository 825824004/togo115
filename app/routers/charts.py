from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services import charts


router = APIRouter(prefix="/api/charts", tags=["charts"])


class ChartSubscribeRequest(BaseModel):
    platform: str  # douban | maoyan
    kind: str = "movie"  # douban: movie|tv ; maoyan: hot|coming|boxoffice
    limit: int = 20


@router.post("/subscribe")
async def chart_subscribe(body: ChartSubscribeRequest) -> dict[str, Any]:
    return await charts.subscribe_chart(body.platform, body.kind, body.limit)


@router.get("/preview")
async def chart_preview(
    platform: str = Query(..., pattern="^(douban|maoyan)$"),
    kind: str = Query("movie"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    items = await charts.fetch_chart(platform, kind, limit)
    return {"ok": True, "platform": platform, "kind": kind, "count": len(items), "items": items}
