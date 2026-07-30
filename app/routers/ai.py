from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import current_user
from app.services.ai.chat import chat_completion, chat_completion_stream
from app.services.ai.config import get_ai_status, mask_ai_config

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list, max_length=40)
    stream: bool = False


@router.get("/api/ai/status")
async def ai_status(user: dict = Depends(current_user)) -> dict:
    return get_ai_status()


@router.get("/api/ai/config")
async def ai_config(user: dict = Depends(current_user)) -> dict:
    return {"ok": True, "config": mask_ai_config()}


@router.post("/api/ai/chat")
async def ai_chat(payload: ChatRequest, user: dict = Depends(current_user)) -> dict:
    messages = [item.model_dump(exclude_none=True) for item in payload.messages]
    if payload.stream:
        # Prefer dedicated stream endpoint; still support flag for simple clients.
        return await chat_completion(messages)
    return await chat_completion(messages)


@router.post("/api/ai/chat/stream")
async def ai_chat_stream(payload: ChatRequest, user: dict = Depends(current_user)) -> StreamingResponse:
    messages = [item.model_dump(exclude_none=True) for item in payload.messages]

    async def event_generator():
        async for event in chat_completion_stream(messages):
            name = event.get("event") or "message"
            data = event.get("data") if isinstance(event.get("data"), dict) else {"value": event.get("data")}
            yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
