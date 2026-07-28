from __future__ import annotations

import asyncio
from typing import Any

from app.db import add_log


def classify_client_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc!s} {exc!r}".casefold()
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in text or "timed out" in text:
        return "timeout"
    if (
        "authkeyduplicated" in text
        or "auth_key_duplicated" in text
        or "auth key duplicated" in text
        or "two different ip addresses" in text
        or "same session exclusively" in text
        or "session file was used under two different ip addresses" in text
    ):
        return "session-duplicated"
    if "api id/api hash" in text or "尚未配置" in text or "missing-config" in text:
        return "missing-config"
    if "database is locked" in text or "database table is locked" in text or "database locked" in text:
        return "session-locked"
    if (
        "file is not a database" in text
        or "database disk image is malformed" in text
        or "malformed" in text
        or "corrupt" in text
        or "no such table" in text
    ):
        return "session-corrupt"
    if (
        "auth key" in text
        or "unauthorized" in text
        or "session revoked" in text
        or "user deactivated" in text
        or "not logged in" in text
    ):
        return "auth"
    if (
        "proxy" in text
        or "socks" in text
        or "connection refused" in text
        or "connection reset" in text
        or "network" in text
        or "host unreachable" in text
        or "name or service not known" in text
        or "temporary failure" in text
        or "ssl" in text
        or "tls" in text
    ):
        return "network-or-proxy"
    return "unknown"


def client_error_message(category: str, exc: Exception) -> str:
    raw = str(exc).strip()
    if raw:
        return raw
    if category == "timeout":
        return "连接 Telegram 超时，请检查代理是否可用，或稍后重试。"
    if category == "network-or-proxy":
        return "无法连接 Telegram，请检查网络或代理配置。"
    if category == "session-locked":
        return "Telegram 会话文件正忙，系统会自动重试。"
    if category == "session-corrupt":
        return "Telegram 会话文件异常，系统会隔离旧会话后重试。"
    if category == "session-duplicated":
        return "Telegram 会话已失效，请重新登录。"
    return repr(exc)


def client_error_hint(category: str, configured: dict[str, Any]) -> str | None:
    if category == "timeout":
        if configured.get("proxy_enabled"):
            return "当前已为 Telegram 启用代理；如果持续超时，请检查代理地址、端口和容器到代理的连通性。"
        return "当前 Telegram 未启用代理；如果部署环境无法直连 Telegram，请在代理设置里勾选 Telegram。"
    if category == "network-or-proxy":
        return "请确认代理服务可从当前部署环境访问，且协议为 http、https、socks4 或 socks5。"
    if category in {"session-corrupt", "session-duplicated"}:
        return "旧会话已不可用，请重新扫码或重新发送验证码登录。"
    return None


def log_client_init_failure(
    *,
    exc: Exception,
    category: str,
    action: str,
    recovered: bool,
    configured: dict[str, Any],
    attempt: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    message = client_error_message(category, exc)
    payload: dict[str, Any] = {
        "category": category,
        "error": message,
        "error_type": type(exc).__name__,
        "error_repr": repr(exc),
        "configured": configured,
        "action": action,
        "recovered": recovered,
    }
    hint = client_error_hint(category, configured)
    if hint:
        payload["hint"] = hint
    if attempt is not None:
        payload["attempt"] = attempt
    if extra:
        payload.update(extra)
    add_log("warning", "telegram", "Telegram 客户端初始化失败", payload)
