from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.db import add_log
from app.services.ai.config import get_ai_config, get_ai_status
from app.services.ai.tools import TOOL_DEFINITIONS, execute_tool

MAX_TOOL_ROUNDS = 6
MAX_HISTORY_MESSAGES = 30


async def chat_completion(messages: list[dict[str, Any]]) -> dict[str, Any]:
    status = get_ai_status()
    if not status.get("ready"):
        return {
            "ok": False,
            "error": status.get("message") or "AI 未就绪",
            "reply": status.get("message") or "AI 未就绪",
            "tool_calls": [],
        }

    cfg = get_ai_config()
    working = _prepare_messages(messages, cfg["system_prompt"])
    tool_trace: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=90.0) as client:
        for _round in range(MAX_TOOL_ROUNDS):
            data = await _request_chat(client, cfg, working, stream=False)
            message = ((data.get("choices") or [{}])[0].get("message")) or {}
            tool_calls = message.get("tool_calls") or []
            content = (message.get("content") or "").strip()

            if tool_calls:
                working.append(
                    {
                        "role": "assistant",
                        "content": message.get("content") or "",
                        "tool_calls": tool_calls,
                    }
                )
                for call in tool_calls:
                    tool_name = ((call.get("function") or {}).get("name")) or ""
                    raw_args = ((call.get("function") or {}).get("arguments")) or "{}"
                    tool_result = await execute_tool(tool_name, raw_args)
                    tool_trace.append({"name": tool_name, "arguments": raw_args, "result": tool_result})
                    working.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id") or tool_name,
                            "name": tool_name,
                            "content": json.dumps(tool_result, ensure_ascii=False),
                        }
                    )
                continue

            if not content:
                content = "（模型未返回文本）"
            add_log("info", "ai", "AI 对话完成", {"tools": len(tool_trace), "model": cfg.get("model")})
            return {
                "ok": True,
                "reply": content,
                "model": cfg.get("model"),
                "tool_calls": tool_trace,
            }

    return {
        "ok": False,
        "error": "工具调用轮次过多",
        "reply": "工具调用轮次过多，请简化问题后重试。",
        "tool_calls": tool_trace,
    }


async def chat_completion_stream(messages: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE-friendly event dicts: meta / delta / tool / done / error."""
    status = get_ai_status()
    if not status.get("ready"):
        yield {"event": "error", "data": {"message": status.get("message") or "AI 未就绪"}}
        return

    cfg = get_ai_config()
    working = _prepare_messages(messages, cfg["system_prompt"])
    tool_trace: list[dict[str, Any]] = []
    yield {"event": "meta", "data": {"model": cfg.get("model"), "base_url": cfg.get("base_url")}}

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            for _round in range(MAX_TOOL_ROUNDS):
                # Non-stream tool planning rounds, then stream the final text when no tools remain.
                data = await _request_chat(client, cfg, working, stream=False)
                message = ((data.get("choices") or [{}])[0].get("message")) or {}
                tool_calls = message.get("tool_calls") or []
                if tool_calls:
                    working.append(
                        {
                            "role": "assistant",
                            "content": message.get("content") or "",
                            "tool_calls": tool_calls,
                        }
                    )
                    for call in tool_calls:
                        tool_name = ((call.get("function") or {}).get("name")) or ""
                        raw_args = ((call.get("function") or {}).get("arguments")) or "{}"
                        yield {
                            "event": "tool",
                            "data": {"name": tool_name, "status": "running", "arguments": raw_args},
                        }
                        tool_result = await execute_tool(tool_name, raw_args)
                        tool_trace.append({"name": tool_name, "arguments": raw_args, "result": tool_result})
                        yield {
                            "event": "tool",
                            "data": {"name": tool_name, "status": "done", "result": tool_result},
                        }
                        working.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.get("id") or tool_name,
                                "name": tool_name,
                                "content": json.dumps(tool_result, ensure_ascii=False),
                            }
                        )
                    continue

                # Final answer — stream if provider supports it, else chunk locally.
                async for delta in _stream_final_answer(client, cfg, working):
                    if delta:
                        yield {"event": "delta", "data": {"text": delta}}
                yield {"event": "done", "data": {"ok": True, "tool_calls": tool_trace, "model": cfg.get("model")}}
                return

        yield {
            "event": "error",
            "data": {"message": "工具调用轮次过多，请简化问题后重试。", "tool_calls": tool_trace},
        }
    except Exception as exc:  # noqa: BLE001
        add_log("error", "ai", "AI 对话失败", {"error": str(exc)})
        yield {"event": "error", "data": {"message": str(exc)}}


def _prepare_messages(messages: list[dict[str, Any]], system_prompt: str) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in messages[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = item.get("content")
        if role not in {"user", "assistant", "system", "tool"}:
            continue
        if content is None:
            content = ""
        entry: dict[str, Any] = {"role": role, "content": str(content)}
        if role == "tool":
            if item.get("tool_call_id"):
                entry["tool_call_id"] = item["tool_call_id"]
            if item.get("name"):
                entry["name"] = item["name"]
        if role == "assistant" and item.get("tool_calls"):
            entry["tool_calls"] = item["tool_calls"]
        cleaned.append(entry)

    # Drop any client-supplied system prompts; inject server-side prompt once.
    cleaned = [m for m in cleaned if m.get("role") != "system"]
    return [{"role": "system", "content": system_prompt}, *cleaned]


async def _request_chat(
    client: httpx.AsyncClient,
    cfg: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    stream: bool,
) -> dict[str, Any]:
    url = f"{cfg['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg.get("temperature", 0.3),
        "max_tokens": cfg.get("max_tokens", 2048),
        "tools": TOOL_DEFINITIONS,
        "tool_choice": "auto",
        "stream": stream,
    }
    response = await client.post(url, headers=headers, json=body)
    if response.status_code >= 400:
        detail = response.text[:500]
        raise RuntimeError(f"LLM API {response.status_code}: {detail}")
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("LLM API 返回格式错误")
    return data


async def _stream_final_answer(
    client: httpx.AsyncClient,
    cfg: dict[str, Any],
    messages: list[dict[str, Any]],
) -> AsyncIterator[str]:
    url = f"{cfg['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg.get("temperature", 0.3),
        "max_tokens": cfg.get("max_tokens", 2048),
        "stream": True,
    }
    try:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code >= 400:
                detail = (await response.aread()).decode("utf-8", errors="ignore")[:500]
                raise RuntimeError(f"LLM API {response.status_code}: {detail}")
            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    payload = line[5:].strip()
                else:
                    continue
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")
                if delta:
                    yield str(delta)
    except Exception:
        # Fallback: non-stream request and yield once.
        data = await _request_chat(client, cfg, messages, stream=False)
        text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        if text:
            yield text
