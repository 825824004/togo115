from __future__ import annotations

import re
from typing import Any

import httpx

from app.db import add_log
from app.services.http_client import shared_async_client
from app.services.integration_state import module_proxy

DOUBAN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Douban's own explore-page JSON API. Stable, structured, and works for both
# movies and TV (the old /tv/chart static page now 404s, so we avoid HTML scraping).
SEARCH_API = "https://movie.douban.com/j/search_subjects"


async def fetch_douban_chart(kind: str = "movie", limit: int = 20) -> list[dict[str, Any]]:
    """抓取豆瓣排行榜（热门电影 / 热门剧集）并解析为订阅候选。

    返回字段：platform, source_kind, title, year, media_type, external_id, url。
    year 为 None（该接口不返回上映年份，下游由 TMDB 匹配补齐）。
    """
    kind = "tv" if str(kind).lower() in ("tv", "show", "series") else "movie"
    proxy = module_proxy("ranking") or module_proxy("tmdb")
    params: dict[str, Any] = {
        "type": kind,
        "tag": "热门",
        "sort": "recommend",
        "page_limit": int(limit or 20),
        "page_start": 0,
    }
    try:
        async with shared_async_client(
            proxy=proxy or None,
            timeout=30,
            follow_redirects=True,
        ) as client:
            res = await client.get(
                SEARCH_API,
                params=params,
                headers={
                    "User-Agent": DOUBAN_UA,
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Referer": "https://movie.douban.com/explore",
                },
            )
            res.raise_for_status()
            data = res.json()
    except Exception as exc:
        add_log("warning", "ranking", "豆瓣榜单抓取失败", {"kind": kind, "error": str(exc)})
        return []

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for s in data.get("subjects", []):
        title = (s.get("title") or "").strip()
        url = s.get("url") or ""
        m = re.search(r"/subject/(\d+)/", url)
        if not title or not m:
            continue
        subject_id = m.group(1)
        if subject_id in seen:
            continue
        seen.add(subject_id)
        items.append(
            {
                "platform": "douban",
                "source_kind": kind,
                "title": title,
                "year": None,
                "media_type": "movie" if kind == "movie" else "tv",
                "external_id": subject_id,
                "url": f"https://movie.douban.com/subject/{subject_id}/",
            }
        )
    return items[: int(limit or 20)]
