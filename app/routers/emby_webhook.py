from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.services import emby_webhook as webhook_service
from app.services.integration_state import get_setting


router = APIRouter(prefix="/api/emby", tags=["emby-webhook"])


class EmbyWebhookSettings(BaseModel):
    enabled: bool = False
    token: str = ""
    auto_subscribe: bool = False
    auto_subscribe_movies: bool = True
    auto_subscribe_series: bool = True
    match_existing: bool = True


@router.post("/webhook")
async def emby_webhook_receive(request: Request) -> dict[str, Any]:
    """Emby Webhook 入口：接收 Emby 媒体库新增事件，回写订阅状态或自动订阅。

    Emby 的 Webhook 插件默认以 ``application/x-www-form-urlencoded`` 推送，
    也兼容 JSON body。两者都会被解析为统一的事件字典。
    """
    payload: dict[str, Any] = {}
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
    if not payload:
        try:
            form = await request.form()
            payload = {str(k): v for k, v in form.items()}
        except Exception:
            payload = {}
    if not payload:
        try:
            text = (await request.body()).decode("utf-8", "ignore")
            if text:
                import json

                payload = json.loads(text)
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return await webhook_service.handle_emby_webhook(payload)


@router.get("/webhook/status")
async def emby_webhook_status() -> dict[str, Any]:
    config = webhook_service.emby_webhook_config()
    events = webhook_service.recent_webhook_events(5)
    return {
        "ok": True,
        "config": config,
        "recent_events": events,
        "webhook_url": "/api/emby/webhook",
    }


@router.get("/webhook/events")
async def emby_webhook_events(limit: int = 50) -> dict[str, Any]:
    events = webhook_service.recent_webhook_events(limit)
    return {"ok": True, "count": len(events), "events": events}


@router.put("/webhook/settings")
async def emby_webhook_save_settings(body: EmbyWebhookSettings) -> dict[str, Any]:
    from app.db import save_setting

    value = body.model_dump()
    save_setting("emby_webhook", value)
    return {"ok": True, "config": value}
