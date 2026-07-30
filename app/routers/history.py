from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.services import history_cache


router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/search")
async def history_search(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(30, ge=1, le=200),
    source: str | None = Query(None, description="限定来源（Telegram 频道/群组标识）"),
    only_115: bool = Query(False, description="仅返回含 115 分享链接的消息"),
) -> dict[str, Any]:
    results = history_cache.search_historical_messages(q, limit=limit, source=source, only_with_115=only_115)
    return {"ok": True, "query": q, "count": len(results), "results": results}


@router.get("/stats")
async def history_stats() -> dict[str, Any]:
    return history_cache.history_cache_stats()
