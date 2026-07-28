from __future__ import annotations

import time
from typing import Any

# Process-local hit scores so later searches in this worker prefer productive dialogs.
_PROCESS_DIALOG_HIT_SCORES: dict[str, int] = {}
# source -> monotonic deadline while dialog is demoted after slow/timeout behavior.
_PROCESS_DIALOG_COOLDOWN_UNTIL: dict[str, float] = {}
# source -> EWMA latency ms for ranking.
_PROCESS_DIALOG_LATENCY_MS: dict[str, float] = {}

SLOW_DIALOG_MS = 2500.0
SLOW_DIALOG_COOLDOWN_SECONDS = 120.0
LATENCY_EWMA_ALPHA = 0.35


def dialog_source_key(dialog: dict[str, Any] | str | None) -> str:
    if isinstance(dialog, dict):
        return str(dialog.get("canonical") or dialog.get("source") or "").strip()
    return str(dialog or "").strip()


def note_dialog_hit(source: str, amount: int = 1) -> None:
    key = str(source or "").strip()
    if not key or amount <= 0:
        return
    _PROCESS_DIALOG_HIT_SCORES[key] = int(_PROCESS_DIALOG_HIT_SCORES.get(key, 0) or 0) + int(amount)
    # Successful hits clear cooldown so productive dialogs stay preferred.
    _PROCESS_DIALOG_COOLDOWN_UNTIL.pop(key, None)


def note_dialog_latency(source: str, latency_ms: float | int, *, had_hits: bool = False) -> None:
    """Track dialog latency and temporarily demote consistently slow sources."""
    key = str(source or "").strip()
    if not key:
        return
    sample = max(0.0, float(latency_ms or 0))
    prev = float(_PROCESS_DIALOG_LATENCY_MS.get(key, sample) or sample)
    ewma = (LATENCY_EWMA_ALPHA * sample) + ((1.0 - LATENCY_EWMA_ALPHA) * prev)
    _PROCESS_DIALOG_LATENCY_MS[key] = ewma
    if had_hits:
        _PROCESS_DIALOG_COOLDOWN_UNTIL.pop(key, None)
        return
    if sample >= SLOW_DIALOG_MS or ewma >= SLOW_DIALOG_MS:
        _PROCESS_DIALOG_COOLDOWN_UNTIL[key] = time.monotonic() + SLOW_DIALOG_COOLDOWN_SECONDS


def dialog_hit_score(source: str, extra_scores: dict[str, int] | None = None) -> int:
    key = str(source or "").strip()
    if not key:
        return 0
    score = int(_PROCESS_DIALOG_HIT_SCORES.get(key, 0) or 0)
    if extra_scores:
        score += int(extra_scores.get(key, 0) or 0)
    return score


def dialog_on_cooldown(source: str, now: float | None = None) -> bool:
    key = str(source or "").strip()
    if not key:
        return False
    until = float(_PROCESS_DIALOG_COOLDOWN_UNTIL.get(key, 0.0) or 0.0)
    if until <= 0:
        return False
    current = time.monotonic() if now is None else now
    if until <= current:
        _PROCESS_DIALOG_COOLDOWN_UNTIL.pop(key, None)
        return False
    return True


def dialog_latency_ms(source: str) -> float:
    key = str(source or "").strip()
    if not key:
        return 0.0
    return float(_PROCESS_DIALOG_LATENCY_MS.get(key, 0.0) or 0.0)


def rank_dialogs(
    dialogs: list[dict[str, Any]],
    *,
    preferred_sources: list[str] | None = None,
    hit_scores: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Rank dialogs: preferred first, then not-cooling, higher hits, lower latency."""
    if not dialogs:
        return []
    preferred = {
        str(item).strip()
        for item in (preferred_sources or [])
        if str(item).strip()
    }
    extra = hit_scores or {}
    now = time.monotonic()

    def sort_key(dialog: dict[str, Any]) -> tuple[int, int, int, float, str]:
        source = dialog_source_key(dialog)
        preferred_rank = 0 if source and source in preferred else 1
        cooldown_rank = 1 if dialog_on_cooldown(source, now) else 0
        score = dialog_hit_score(source, extra)
        latency = dialog_latency_ms(source)
        return (preferred_rank, cooldown_rank, -score, latency, source)

    return sorted(dialogs, key=sort_key)


def clear_process_dialog_hit_scores() -> None:
    """Test helper."""
    _PROCESS_DIALOG_HIT_SCORES.clear()
    _PROCESS_DIALOG_COOLDOWN_UNTIL.clear()
    _PROCESS_DIALOG_LATENCY_MS.clear()
