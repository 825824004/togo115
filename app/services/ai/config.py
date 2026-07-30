from __future__ import annotations

from typing import Any

from app.services.settings_store import list_settings

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_SYSTEM_PROMPT = """你是 ToGo115 的 AI 助手，帮助用户管理 115 网盘媒体订阅与追新。

你可以：
1. 查询当前订阅列表、资源与失败任务
2. 通过 TMDB 搜索影视并创建订阅
3. 触发某部作品的搜索/追新
4. 暂停、恢复或取消订阅
5. 解释系统功能与配置建议

规则：
- 优先调用工具获取真实数据，不要编造订阅 ID 或结果
- 创建订阅前尽量用 TMDB 确认标题、媒体类型和年份
- 回复简洁，使用中文，必要时用列表
- 涉及危险操作（取消订阅）先确认再执行；工具已要求用户意图明确时才调用
- 如果 AI 或外部 API 未配置，明确告知用户去「设置 → AI 助手」填写
"""


def get_ai_config() -> dict[str, Any]:
    settings = list_settings()
    raw = settings.get("ai", {}).get("value") or {}
    if not isinstance(raw, dict):
        raw = {}
    base_url = str(raw.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    return {
        "enabled": bool(raw.get("enabled", True)),
        "base_url": base_url or DEFAULT_BASE_URL,
        "api_key": str(raw.get("api_key") or "").strip(),
        "model": str(raw.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "system_prompt": str(raw.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip() or DEFAULT_SYSTEM_PROMPT,
        "temperature": _as_float(raw.get("temperature"), 0.3),
        "max_tokens": int(_as_float(raw.get("max_tokens"), 2048) or 2048),
    }


def mask_ai_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(config or get_ai_config())
    key = str(cfg.get("api_key") or "")
    if key:
        cfg["api_key_set"] = True
        cfg["api_key_preview"] = f"{key[:4]}…{key[-4:]}" if len(key) > 8 else "****"
    else:
        cfg["api_key_set"] = False
        cfg["api_key_preview"] = ""
    cfg.pop("api_key", None)
    return cfg


def get_ai_status() -> dict[str, Any]:
    cfg = get_ai_config()
    ready = bool(cfg.get("enabled") and cfg.get("api_key") and cfg.get("base_url") and cfg.get("model"))
    return {
        "ok": True,
        "ready": ready,
        "enabled": bool(cfg.get("enabled")),
        "base_url": cfg.get("base_url"),
        "model": cfg.get("model"),
        "api_key_set": bool(cfg.get("api_key")),
        "message": "" if ready else "请先在设置 → AI 助手中配置 API Key 与模型",
    }


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
