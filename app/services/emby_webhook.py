from __future__ import annotations

import re
from typing import Any

from app.db import add_log, db, json_dumps, utc_now
from app.services.integration_state import get_setting
from app.services.subscription.match.matching import compact_match_text


def emby_webhook_config() -> dict[str, Any]:
    config = get_setting("emby_webhook")
    if not isinstance(config, dict):
        config = {}
    return {
        "enabled": bool(config.get("enabled", False)),
        "token": str(config.get("token") or "").strip(),
        "auto_subscribe": bool(config.get("auto_subscribe", False)),
        "auto_subscribe_movies": bool(config.get("auto_subscribe_movies", True)),
        "auto_subscribe_series": bool(config.get("auto_subscribe_series", True)),
        "match_existing": bool(config.get("match_existing", True)),
    }


def parse_emby_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize an Emby webhook payload into a stable event dict.

    Emby's Webhook plugin posts ``application/x-www-form-urlencoded`` with keys
    like ``NotificationType``, ``ItemType``, ``Name``, ``SeriesName``,
    ``ProductionYear``, ``SeasonNumber``, ``EpisodeNumber``, ``ItemId`` and
    optional ``Provider_tmdb`` / ``Provider_Tmdb``.
    """

    def first(key: str) -> str:
        value = raw.get(key)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        return str(value or "").strip()

    notification = first("NotificationType") or first("Event") or first("Type")
    item_type = (first("ItemType") or first("ItemTypeValue") or "").strip()
    name = first("Name") or first("Title")
    series_name = first("SeriesName")
    year_raw = first("ProductionYear") or (first("PremiereDate") or "")[:4]
    season = _to_int(first("SeasonNumber"))
    episode = _to_int(first("EpisodeNumber"))
    item_id = first("ItemId") or first("ItemIdValue")
    tmdb_raw = first("Provider_tmdb") or first("Provider_Tmdb") or first("TmdbId") or first("Provider_tmdb_id")
    tmdb_id = _to_int(re.sub(r"[^0-9]", "", tmdb_raw))
    overview = first("Overview") or first("Description")
    poster = first("ImageUrl") or first("ImagePrimary")

    # For episodes the human title lives in SeriesName; Name is the episode title.
    if item_type == "Episode":
        title = series_name or name
        media_type = "tv"
    elif item_type == "Season":
        title = series_name or name
        media_type = "tv"
    elif item_type == "Series":
        title = name
        media_type = "tv"
    elif item_type == "Movie":
        title = name
        media_type = "movie"
    else:
        # Unknown item type: still try to capture movies/series by name.
        title = series_name or name
        media_type = "movie" if "movie" in (notification + item_type).lower() else "tv"

    year = _to_int(year_raw)
    return {
        "notification_type": notification,
        "item_type": item_type,
        "media_type": media_type,
        "title": title,
        "year": year,
        "series_name": series_name,
        "season": season,
        "episode": episode,
        "item_id": item_id,
        "tmdb_id": tmdb_id,
        "overview": overview,
        "poster_url": poster,
    }


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


def _is_add_event(event: dict[str, Any]) -> bool:
    notification = (event.get("notification_type") or "").lower()
    if not notification:
        return True
    return any(token in notification for token in ("newitem", "itemadded", "added", "library.new", "add"))


def _find_existing_subscription(event: dict[str, Any]) -> dict | None:
    title = compact_match_text(event.get("title") or "")
    media_type = event.get("media_type")
    tmdb_id = event.get("tmdb_id")
    if not title and not tmdb_id:
        return None
    with db() as conn:
        if tmdb_id:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE tmdb_id = ? AND media_type = ? LIMIT 1",
                (tmdb_id, media_type),
            ).fetchone()
            if row:
                return dict(row)
        if title:
            candidates = conn.execute(
                "SELECT * FROM subscriptions WHERE media_type = ?", (media_type,)
            ).fetchall()
            for row in candidates:
                sub_title = compact_match_text(row.get("title") or "")
                if sub_title and (sub_title == title or title in sub_title or sub_title in title):
                    return dict(row)
    return None


async def handle_emby_webhook(raw: dict[str, Any]) -> dict[str, Any]:
    config = emby_webhook_config()
    if not config["enabled"]:
        return {"ok": False, "ignored": True, "reason": "webhook_disabled"}

    # Optional shared-secret check (Emby webhook can embed a custom Token field).
    if config["token"]:
        provided = str(raw.get("Token") or raw.get("token") or "").strip()
        if provided != config["token"]:
            return {"ok": False, "ignored": True, "reason": "token_mismatch"}

    event = parse_emby_payload(raw)
    if not event.get("title"):
        return {"ok": False, "ignored": True, "reason": "no_title"}

    action = "ignored"
    matched_id: int | None = None
    detail = ""

    if not _is_add_event(event):
        action = "non_add_event"
        detail = event.get("notification_type") or ""
    else:
        existing = _find_existing_subscription(event) if config["match_existing"] else None
        if existing:
            matched_id = int(existing["id"])
            _writeback_subscription(existing, event)
            action = "writeback"
            detail = f"更新订阅 #{matched_id} 入库状态"
        elif config["auto_subscribe"] and _auto_subscribe_allowed(config, event):
            created = await _auto_create_subscription(event)
            if created:
                matched_id = int(created.get("id") or 0) or None
                action = "auto_subscribed"
                detail = f"自动创建订阅 #{matched_id}（来自 Emby Webhook）"
            else:
                action = "auto_subscribe_failed"
                detail = "自动订阅创建失败（去重或参数问题）"

    _record_event(event, action, matched_id, detail, raw)
    add_log(
        "info",
        "emby_webhook",
        f"收到 Emby Webhook：{event.get('title')}（{action}）",
        {"item_type": event.get("item_type"), "matched_id": matched_id},
    )
    return {
        "ok": True,
        "action": action,
        "title": event.get("title"),
        "media_type": event.get("media_type"),
        "matched_subscription_id": matched_id,
        "detail": detail,
    }


def _auto_subscribe_allowed(config: dict[str, Any], event: dict[str, Any]) -> bool:
    if event.get("media_type") == "movie":
        return bool(config.get("auto_subscribe_movies"))
    return bool(config.get("auto_subscribe_series"))


def _writeback_subscription(subscription: dict, event: dict[str, Any]) -> None:
    sub_id = int(subscription["id"])
    media_type = subscription.get("media_type")
    now = utc_now()
    with db() as conn:
        if media_type == "movie":
            conn.execute(
                "UPDATE subscriptions SET in_library = 1, emby_count = MAX(emby_count, 1), updated_at = ? WHERE id = ?",
                (now, sub_id),
            )
        else:
            current = int(subscription.get("emby_count") or 0)
            # An episode add bumps the owned count by one; a series/missing add marks in-library.
            new_count = current + (1 if event.get("item_type") == "Episode" else 0)
            conn.execute(
                "UPDATE subscriptions SET in_library = 1, emby_count = MAX(emby_count, ?), updated_at = ? WHERE id = ?",
                (new_count, now, sub_id),
            )


async def _auto_create_subscription(event: dict[str, Any]) -> dict | None:
    from app.schemas import SubscriptionCreate
    from app.services.subscription import create_subscription as _create

    tmdb_id = event.get("tmdb_id")
    if not tmdb_id and event.get("title"):
        tmdb_id = await _resolve_tmdb_id(event.get("title"), event.get("media_type"), event.get("year"))
    payload = SubscriptionCreate(
        title=event["title"],
        media_type=event["media_type"],  # type: ignore[arg-type]
        tmdb_id=tmdb_id,
        poster_url=event.get("poster_url"),
        overview=event.get("overview"),
        release_year=event.get("year"),
        keywords=[event["title"]],
    )
    created = await _create(payload)
    if created and created.get("id"):
        _tag_auto_source(int(created["id"]), event)
    return created or None


async def _resolve_tmdb_id(title: str, media_type: str, year: int | None) -> int | None:
    try:
        from app.services.adapters.media_tmdb import TmdbAdapter

        results = await TmdbAdapter().search(title, media_type)
    except Exception as exc:
        add_log("debug", "emby_webhook", "Webhook 自动订阅 TMDB 解析失败", {"title": title, "error": str(exc)})
        return None
    for item in results[:8]:
        candidate_title = (item.get("title") or item.get("name") or "").strip()
        candidate_year = (item.get("release_date") or item.get("first_air_date") or "")[:4]
        if candidate_title and candidate_title == title:
            if not year or not candidate_year or int(candidate_year) == int(year):
                return int(item.get("id") or 0) or None
    # Fallback: first result.
    if results:
        return int(results[0].get("id") or 0) or None
    return None


def _tag_auto_source(subscription_id: int, event: dict[str, Any]) -> None:
    try:
        with db() as conn:
            conn.execute(
                "UPDATE subscriptions SET auto_source = 'emby_webhook', auto_source_detail = ?, updated_at = ? WHERE id = ?",
                (json_dumps({"item_id": event.get("item_id"), "item_type": event.get("item_type")}), utc_now(), subscription_id),
            )
    except Exception:
        pass


def _record_event(event: dict[str, Any], action: str, matched_id: int | None, detail: str, raw: dict[str, Any]) -> None:
    try:
        with db() as conn:
            conn.execute(
                """
                INSERT INTO emby_webhook_events
                (event_type, item_type, title, year, series_name, season, episode, item_id, tmdb_id,
                 matched_subscription_id, action, detail, payload, received_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("notification_type"),
                    event.get("item_type"),
                    event.get("title"),
                    event.get("year"),
                    event.get("series_name"),
                    event.get("season"),
                    event.get("episode"),
                    event.get("item_id"),
                    event.get("tmdb_id"),
                    matched_id,
                    action,
                    detail,
                    json_dumps(raw)[:4000],
                    utc_now(),
                ),
            )
    except Exception as exc:
        add_log("warning", "emby_webhook", "写入 Webhook 事件记录失败", {"error": str(exc)})


def recent_webhook_events(limit: int = 30) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM emby_webhook_events ORDER BY id DESC LIMIT ?", (max(1, min(int(limit or 30), 200)),)
        ).fetchall()
    return [dict(row) for row in rows]
