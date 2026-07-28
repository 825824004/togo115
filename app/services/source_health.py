from __future__ import annotations

import time
from typing import Any

# Process-level source health for RSS/magnet fallback demotion.
COOLDOWN_SECONDS = 180.0
FAILURE_THRESHOLD = 2
MAX_ENTRIES = 256

_failures: dict[str, int] = {}
_cooldown_until: dict[str, float] = {}
_latency_ms: dict[str, float] = {}


def _key(source: Any) -> str:
    if isinstance(source, dict):
        return str(source.get("name") or source.get("url") or source.get("id") or "").strip().casefold()
    return str(source or "").strip().casefold()


def note_source_success(source: Any, latency_ms: float | int = 0) -> None:
    key = _key(source)
    if not key:
        return
    _failures[key] = 0
    _cooldown_until.pop(key, None)
    sample = max(0.0, float(latency_ms or 0))
    prev = float(_latency_ms.get(key, sample) or sample)
    _latency_ms[key] = (0.4 * sample) + (0.6 * prev)


def note_source_failure(source: Any, *, timeout: bool = False) -> None:
    key = _key(source)
    if not key:
        return
    amount = 2 if timeout else 1
    count = int(_failures.get(key, 0) or 0) + amount
    _failures[key] = count
    if count >= FAILURE_THRESHOLD:
        _cooldown_until[key] = time.monotonic() + COOLDOWN_SECONDS
    _purge()


def source_on_cooldown(source: Any) -> bool:
    key = _key(source)
    if not key:
        return False
    until = float(_cooldown_until.get(key, 0.0) or 0.0)
    if until <= 0:
        return False
    if until <= time.monotonic():
        _cooldown_until.pop(key, None)
        _failures[key] = 0
        return False
    return True


def filter_ready_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ready = [item for item in sources if not source_on_cooldown(item)]
    return ready or list(sources)


def rank_sources_by_health(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(item: dict[str, Any]) -> tuple[int, float, str]:
        key = _key(item)
        cooling = 1 if source_on_cooldown(item) else 0
        latency = float(_latency_ms.get(key, 0.0) or 0.0)
        return (cooling, latency, key)

    return sorted(sources, key=sort_key)


def clear_source_health() -> None:
    _failures.clear()
    _cooldown_until.clear()
    _latency_ms.clear()


def _purge() -> None:
    if len(_failures) <= MAX_ENTRIES and len(_cooldown_until) <= MAX_ENTRIES:
        return
    now = time.monotonic()
    for key, until in list(_cooldown_until.items()):
        if until <= now:
            _cooldown_until.pop(key, None)
            _failures.pop(key, None)
    if len(_failures) > MAX_ENTRIES:
        overflow = sorted(_failures.items(), key=lambda item: item[1], reverse=True)[MAX_ENTRIES:]
        for key, _ in overflow:
            _failures.pop(key, None)
            _cooldown_until.pop(key, None)
            _latency_ms.pop(key, None)
