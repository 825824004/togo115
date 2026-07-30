from __future__ import annotations

import json
from typing import Any

from app.schemas import SubscriptionCreate, SubscriptionUpdate
from app.services import application as app_actions
from app.services.media_catalog import tmdb_search
from app.services.resource_queries import list_recent_resources


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_subscriptions",
            "description": "列出当前订阅，可按状态或关键词过滤",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["all", "active", "paused", "completed"],
                        "description": "订阅状态过滤，默认 all",
                    },
                    "query": {
                        "type": "string",
                        "description": "按标题关键词模糊过滤",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回条数，默认 20，最大 50",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_subscription",
            "description": "创建影视订阅并自动进入后台搜索。标题必填。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "作品中文/原名标题"},
                    "media_type": {
                        "type": "string",
                        "enum": ["tv", "movie"],
                        "description": "tv=剧集, movie=电影，默认 tv",
                    },
                    "tmdb_id": {"type": "integer", "description": "TMDB ID，可选"},
                    "poster_url": {"type": "string"},
                    "overview": {"type": "string"},
                    "release_year": {"type": "integer"},
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "搜索关键词，默认用标题",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_subscription_status",
            "description": "暂停、恢复或标记完成某个订阅",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "integer"},
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused", "completed"],
                    },
                },
                "required": ["subscription_id", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_subscription",
            "description": "删除/取消某个订阅（不可恢复）",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "integer"},
                    "confirm": {
                        "type": "boolean",
                        "description": "必须为 true 才会真正删除",
                    },
                },
                "required": ["subscription_id", "confirm"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_subscription",
            "description": "对指定订阅触发一次后台资源搜索",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscription_id": {"type": "integer"},
                },
                "required": ["subscription_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_all_subscriptions",
            "description": "对全部活跃订阅触发一次后台重搜",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_tmdb",
            "description": "在 TMDB 搜索影视，用于确认作品信息后再订阅",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "media_type": {
                        "type": "string",
                        "enum": ["multi", "tv", "movie"],
                        "description": "默认 multi",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_resources",
            "description": "查看最近命中/转存的资源记录",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "默认 15，最大 40"},
                    "status": {
                        "type": "string",
                        "description": "可选：pending/saved/failed/delivered 等状态过滤",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_overview",
            "description": "获取系统概览：订阅数、资源数、失败任务等",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_historical_messages",
            "description": "在 Telegram 历史消息缓存库中按关键词检索已监控频道/群组的消息（含 115 分享链接的资源），用于本地快速找资源而无需重复请求 TG API。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，如剧名或资源名"},
                    "limit": {"type": "integer", "description": "最多返回条数，默认 20，最大 100"},
                    "only_115": {"type": "boolean", "description": "仅返回含 115 分享链接的消息，默认 false"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "subscribe_douban_chart",
            "description": "订阅豆瓣榜单（热门电影/热门剧集）。自动抓取榜单并批量创建订阅，已存在则跳过。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["movie", "tv"],
                        "description": "movie=热门电影, tv=热门剧集，默认 movie",
                    },
                    "limit": {"type": "integer", "description": "抓取前 N 条，默认 20，最大 100"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "subscribe_maoyan_chart",
            "description": "订阅猫眼榜单（热映/待映/票房榜）。自动抓取榜单并批量创建电影订阅，已存在则跳过。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["hot", "coming", "boxoffice"],
                        "description": "hot=热映, coming=待映, boxoffice=票房榜，默认 hot",
                    },
                    "limit": {"type": "integer", "description": "抓取前 N 条，默认 20，最大 100"},
                },
            },
        },
    },
]


async def execute_tool(name: str, arguments: dict[str, Any] | str | None) -> dict[str, Any]:
    args = _normalize_args(arguments)
    try:
        if name == "list_subscriptions":
            return await _tool_list_subscriptions(args)
        if name == "create_subscription":
            return await _tool_create_subscription(args)
        if name == "update_subscription_status":
            return await _tool_update_status(args)
        if name == "cancel_subscription":
            return await _tool_cancel(args)
        if name == "search_subscription":
            return await _tool_search_one(args)
        if name == "search_all_subscriptions":
            return app_actions.schedule_search_all_active_subscriptions(force=True)
        if name == "search_tmdb":
            return await _tool_search_tmdb(args)
        if name == "list_recent_resources":
            return await _tool_list_resources(args)
        if name == "get_system_overview":
            return await _tool_overview()
        if name == "search_historical_messages":
            return await _tool_search_history(args)
        if name == "subscribe_douban_chart":
            return await _tool_subscribe_chart("douban", args)
        if name == "subscribe_maoyan_chart":
            return await _tool_subscribe_chart("maoyan", args)
        return {"ok": False, "error": f"未知工具: {name}"}
    except Exception as exc:  # noqa: BLE001 - surface tool errors to the model
        return {"ok": False, "error": str(exc), "tool": name}


def _normalize_args(arguments: dict[str, Any] | str | None) -> dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _compact_subscription(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "media_type": item.get("media_type"),
        "status": item.get("status"),
        "release_year": item.get("release_year"),
        "keywords": item.get("keywords") or [],
        "in_library": item.get("in_library"),
        "emby_count": item.get("emby_count"),
        "tmdb_total_count": item.get("tmdb_total_count"),
        "last_checked_at": item.get("last_checked_at"),
        "tmdb_id": item.get("tmdb_id"),
    }


async def _tool_list_subscriptions(args: dict[str, Any]) -> dict[str, Any]:
    status = str(args.get("status") or "all").strip().lower()
    query = str(args.get("query") or "").strip().lower()
    limit = max(1, min(int(args.get("limit") or 20), 50))
    items = app_actions.list_subscriptions(include_completed=True)
    if status != "all":
        items = [item for item in items if str(item.get("status") or "") == status]
    if query:
        items = [item for item in items if query in str(item.get("title") or "").lower()]
    payload = [_compact_subscription(item) for item in items[:limit]]
    return {"ok": True, "count": len(payload), "total_matched": len(items), "subscriptions": payload}


async def _tool_create_subscription(args: dict[str, Any]) -> dict[str, Any]:
    title = str(args.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "title 不能为空"}
    media_type = str(args.get("media_type") or "tv").strip().lower()
    if media_type not in {"tv", "movie"}:
        media_type = "tv"
    keywords = args.get("keywords")
    if not isinstance(keywords, list):
        keywords = [title]
    keywords = [str(item).strip() for item in keywords if str(item).strip()] or [title]
    payload = SubscriptionCreate(
        title=title,
        media_type=media_type,  # type: ignore[arg-type]
        tmdb_id=args.get("tmdb_id"),
        poster_url=args.get("poster_url"),
        overview=args.get("overview"),
        release_year=args.get("release_year"),
        keywords=keywords,
    )
    created = await app_actions.create_subscription(payload)
    return {"ok": True, "subscription": _compact_subscription(created), "message": "订阅已创建，后台搜索已触发"}


async def _tool_update_status(args: dict[str, Any]) -> dict[str, Any]:
    subscription_id = int(args.get("subscription_id") or 0)
    status = str(args.get("status") or "").strip()
    if not subscription_id or status not in {"active", "paused", "completed"}:
        return {"ok": False, "error": "subscription_id / status 无效"}
    updated = app_actions.update_subscription(subscription_id, SubscriptionUpdate(status=status))  # type: ignore[arg-type]
    return {"ok": True, "subscription": _compact_subscription(updated)}


async def _tool_cancel(args: dict[str, Any]) -> dict[str, Any]:
    subscription_id = int(args.get("subscription_id") or 0)
    confirm = bool(args.get("confirm"))
    if not subscription_id:
        return {"ok": False, "error": "subscription_id 无效"}
    if not confirm:
        return {"ok": False, "error": "需要 confirm=true 才会删除"}
    existing = app_actions.get_subscription(subscription_id)
    if not existing:
        return {"ok": False, "error": "订阅不存在"}
    app_actions.delete_subscription(subscription_id)
    return {"ok": True, "deleted_id": subscription_id, "title": existing.get("title")}


async def _tool_search_one(args: dict[str, Any]) -> dict[str, Any]:
    subscription_id = int(args.get("subscription_id") or 0)
    if not subscription_id:
        return {"ok": False, "error": "subscription_id 无效"}
    existing = app_actions.get_subscription(subscription_id)
    if not existing:
        return {"ok": False, "error": "订阅不存在"}
    result = app_actions.schedule_subscription_search(subscription_id)
    return {"ok": True, "subscription": _compact_subscription(existing), "job": result}


async def _tool_search_tmdb(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query 不能为空"}
    media_type = str(args.get("media_type") or "multi").strip() or "multi"
    data = await tmdb_search(query, media_type)
    results = data.get("results") if isinstance(data, dict) else []
    if not isinstance(results, list):
        results = []
    compact = []
    for item in results[:10]:
        if not isinstance(item, dict):
            continue
        media = item.get("media_type") or media_type
        title = item.get("title") or item.get("name") or item.get("original_title") or item.get("original_name")
        year = (item.get("release_date") or item.get("first_air_date") or "")[:4]
        poster = item.get("poster_path")
        compact.append(
            {
                "tmdb_id": item.get("id"),
                "title": title,
                "media_type": "movie" if media == "movie" else "tv" if media in {"tv", "multi"} else media,
                "year": year or None,
                "overview": (item.get("overview") or "")[:180],
                "poster_url": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
            }
        )
    return {"ok": True, "count": len(compact), "results": compact}


async def _tool_list_resources(args: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 15), 40))
    status = str(args.get("status") or "").strip().lower()
    items = list_recent_resources(limit * 2 if status else limit, 0)
    if status:
        items = [item for item in items if str(item.get("status") or "").lower() == status][:limit]
    else:
        items = items[:limit]
    compact = [
        {
            "id": item.get("id"),
            "subscription_id": item.get("subscription_id"),
            "title": item.get("title"),
            "source": item.get("source"),
            "status": item.get("status"),
            "url": item.get("url"),
            "last_error": item.get("last_error"),
            "created_at": item.get("created_at"),
        }
        for item in items
    ]
    return {"ok": True, "count": len(compact), "resources": compact}


async def _tool_overview() -> dict[str, Any]:
    subscriptions = app_actions.list_subscriptions(include_completed=True)
    resources = list_recent_resources(50, 0)
    failed = app_actions.list_failed_resources()
    by_status: dict[str, int] = {}
    for item in subscriptions:
        key = str(item.get("status") or "unknown")
        by_status[key] = by_status.get(key, 0) + 1
    return {
        "ok": True,
        "subscription_total": len(subscriptions),
        "subscription_by_status": by_status,
        "recent_resources": len(resources),
        "failed_tasks": len(failed),
    }


async def _tool_search_history(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query 不能为空"}
    limit = max(1, min(int(args.get("limit") or 20), 100))
    only_115 = bool(args.get("only_115"))
    from app.services import history_cache

    results = history_cache.search_historical_messages(query, limit=limit, only_with_115=only_115)
    compact = [
        {
            "source": item.get("source"),
            "message_id": item.get("message_id"),
            "message_date": item.get("message_date"),
            "has_115": item.get("has_115"),
            "text": (item.get("text") or "")[:300],
        }
        for item in results
    ]
    return {"ok": True, "query": query, "count": len(compact), "results": compact}


async def _tool_subscribe_chart(platform: str, args: dict[str, Any]) -> dict[str, Any]:
    kind = str(args.get("kind") or ("movie" if platform == "douban" else "hot")).strip()
    limit = max(1, min(int(args.get("limit") or 20), 100))
    from app.services import charts

    return await charts.subscribe_chart(platform, kind, limit)
