from __future__ import annotations

import re
from typing import Any

import httpx

from app.db import add_log
from app.services.http_client import shared_async_client
from app.services.integration_state import module_proxy

MAOYAN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

KIND_URLS: dict[str, str] = {
    "hot": "https://www.maoyan.com/films",
    "coming": "https://www.maoyan.com/films?showType=2",
    "boxoffice": "https://www.maoyan.com/board/1",
}


async def fetch_maoyan_chart(kind: str = "hot", limit: int = 20) -> list[dict[str, Any]]:
    """抓取猫眼榜单（热映 / 待映 / 票房榜）并解析为订阅候选。

    返回字段：platform, source_kind, title, year, media_type(movie), external_id, url。
    """
    key = str(kind).lower()
    if key not in KIND_URLS:
        key = "hot"
    url = KIND_URLS[key]
    proxy = module_proxy("ranking") or module_proxy("tmdb")
    try:
        async with shared_async_client(
            proxy=proxy or None,
            timeout=30,
            follow_redirects=True,
        ) as client:
            res = await client.get(
                url,
                headers={"User-Agent": MAOYAN_UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            )
            res.raise_for_status()
            html = res.text
    except Exception as exc:
        add_log("warning", "ranking", "猫眼榜单抓取失败", {"kind": kind, "error": str(exc)})
        return []

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    # Maoyan renders each chart entry as an anchor with a relative /films/<id>
    # href and a data-val carrying the movieId; the visible title is the anchor text.
    pattern = re.compile(r'<a href="/films/(\d+)"[^>]*data-val="\{movieId:\d+\}">([^<]+)</a>')
    for m in pattern.finditer(html):
        fid = m.group(1)
        if fid in seen:
            continue
        title = m.group(2).strip()
        if not title:
            continue
        seen.add(fid)
        items.append(_build(fid, title, key))
        if len(items) >= int(limit or 20):
            break

    return items


def _build(fid: str, title: str, kind: str) -> dict[str, Any]:
    return {
        "platform": "maoyan",
        "source_kind": kind,
        "title": title,
        "year": None,
        "media_type": "movie",
        "external_id": fid,
        "url": f"https://www.maoyan.com/films/{fid}",
    }
