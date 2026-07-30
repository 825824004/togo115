from __future__ import annotations

from typing import Any

from app.db import add_log, db, json_dumps, utc_now
from app.schemas import SubscriptionCreate
from app.services import application as app_actions
from app.services.sources.ranking import fetch_douban_chart, fetch_maoyan_chart


async def fetch_chart(platform: str, kind: str = "movie", limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 20), 100))
    if platform == "douban":
        return await fetch_douban_chart(kind, limit)
    if platform == "maoyan":
        return await fetch_maoyan_chart(kind, limit)
    return []


async def _resolve_tmdb_id(title: str, media_type: str, year: int | None) -> int | None:
    if not title:
        return None
    try:
        from app.services.adapters.media_tmdb import TmdbAdapter

        results = await TmdbAdapter().search(title, media_type)
    except Exception as exc:
        add_log("debug", "charts", "榜单订阅 TMDB 解析跳过", {"title": title, "error": str(exc)})
        return None
    for item in results[:8]:
        candidate = (item.get("title") or item.get("name") or "").strip()
        candidate_year = (item.get("release_date") or item.get("first_air_date") or "")[:4]
        if candidate and candidate == title:
            if not year or not candidate_year or int(candidate_year) == int(year):
                return int(item.get("id") or 0) or None
    if results:
        return int(results[0].get("id") or 0) or None
    return None


def _tag_auto_source(subscription_id: int, platform: str, item: dict[str, Any]) -> None:
    try:
        with db() as conn:
            conn.execute(
                "UPDATE subscriptions SET auto_source = ?, auto_source_detail = ?, updated_at = ? WHERE id = ?",
                (
                    f"chart:{platform}",
                    json_dumps({"source_kind": item.get("source_kind"), "external_id": item.get("external_id"), "url": item.get("url")}),
                    utc_now(),
                    subscription_id,
                ),
            )
    except Exception:
        pass


async def subscribe_chart(
    platform: str,
    kind: str = "movie",
    limit: int = 20,
    skip_existing: bool = True,
) -> dict[str, Any]:
    """抓取指定平台榜单，解析后批量创建订阅（自动去重）。"""
    items = await fetch_chart(platform, kind, limit)
    if not items:
        return {
            "ok": True,
            "platform": platform,
            "kind": kind,
            "fetched": 0,
            "created": 0,
            "skipped": 0,
            "failed": 0,
            "items": [],
            "message": "榜单为空或抓取失败（检查网络/代理）",
        }

    from app.services.subscription.crud.duplicates import duplicate_subscription

    created: list[dict[str, Any]] = []
    skipped: list[str] = []
    failed: list[str] = []
    errors: list[str] = []

    for item in items:
        title = (item.get("title") or "").strip()
        media_type = item.get("media_type") or "movie"
        if not title:
            continue
        payload = SubscriptionCreate(
            title=title,
            media_type=media_type,  # type: ignore[arg-type]
            release_year=item.get("year"),
            keywords=[title],
        )
        if skip_existing and duplicate_subscription(payload):
            skipped.append(title)
            continue
        tmdb_id = await _resolve_tmdb_id(title, media_type, item.get("year"))
        payload.tmdb_id = tmdb_id
        try:
            created_sub = await app_actions.create_subscription(payload)
            if created_sub and created_sub.get("id"):
                _tag_auto_source(int(created_sub["id"]), platform, item)
                created.append(
                    {
                        "id": created_sub.get("id"),
                        "title": title,
                        "media_type": media_type,
                        "tmdb_id": tmdb_id,
                        "year": item.get("year"),
                    }
                )
            else:
                skipped.append(title)
        except Exception as exc:
            failed.append(title)
            errors.append(f"{title}: {exc}")

    return {
        "ok": True,
        "platform": platform,
        "kind": kind,
        "fetched": len(items),
        "created": len(created),
        "skipped": len(skipped),
        "failed": len(failed),
        "items": created,
        "skipped_titles": skipped[:20],
        "errors": errors[:10],
        "message": f"榜单订阅完成：新增 {len(created)}，跳过 {len(skipped)}，失败 {len(failed)}",
    }
