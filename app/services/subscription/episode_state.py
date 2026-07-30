"""Per-episode state machine for TV subscription missing-list tracking (M1).

This module is the shared backbone for the closed-loop pipeline:

    [1] Subscribe -> [2] Monitor -> [3] Match -> [4] Deliver -> [5] Import/Notify
                                              (M2)        (M4)        (M3 -> here)

It persists one row per expected episode in ``subscription_episode_states`` so the
UI and automation can track exactly which episodes are still wanted, matched,
delivered, or already in the library. Reuse existing episode math from
``app.services.subscription.episode`` rather than recomputing ownership.
"""

from __future__ import annotations

from typing import Any

from app.db import db, row_to_dict, utc_now
from app.services.subscription.crud.rows import get_subscription
from app.services.subscription.episode.keys import (
    _all_tmdb_episode_keys,
    owned_episode_keys,
)
from app.services.subscription.episode.summary import subscription_episode_snapshot


# State lifecycle for a single episode key.
#   wanted      -> not yet found
#   searching   -> a search is currently in flight for this episode
#   matched     -> a candidate resource matched this episode
#   delivered   -> the resource was handed to 115 / delivery succeeded
#   in_library  -> Emby reports the episode as present (M3 webhook)
#   upgraded    -> a higher-quality version superseded the delivered one (M4)
EPISODE_STATES = ("wanted", "searching", "matched", "delivered", "in_library", "upgraded")

# States that represent "we already have movement beyond wanted".
_ADVANCED_STATES = ("matched", "delivered", "in_library", "upgraded")


def recompute_missing(subscription_id: int) -> None:
    """Idempotently (re)build the per-episode state rows for a TV subscription.

    Diffs the expected TMDB episode set against owned episodes and reconciles the
    persisted state without ever downgrading genuine progress:
      * owned -> in_library
      * previously matched/delivered/upgraded -> keep (file still pending import)
      * owned-but-was-delivered edge -> downgrade to delivered (file likely remains)
      * otherwise -> wanted
    """
    sub = get_subscription(subscription_id)
    if not sub or sub.get("media_type") != "tv":
        return
    expected = _all_tmdb_episode_keys(sub)
    owned = owned_episode_keys(sub)
    if not expected:
        return

    with db() as conn:
        rows = conn.execute(
            "SELECT season, episode, state, resource_id, quality_rank "
            "FROM subscription_episode_states WHERE subscription_id = ?",
            (subscription_id,),
        ).fetchall()
    existing = {(r["season"], r["episode"]): r for r in rows}

    now = utc_now()
    upserts: list[tuple] = []
    expected_keys = set(expected)
    for season, episode in expected_keys:
        is_owned = (season, episode) in owned
        old = existing.get((season, episode))
        old_state = old["state"] if old else "wanted"
        if is_owned:
            new_state = "in_library"
            res_id = old["resource_id"] if old else None
            q_rank = old["quality_rank"] if old else None
        elif old_state == "in_library":
            # Ownership dropped (rare); keep the delivered file reference.
            new_state = "delivered"
            res_id = old["resource_id"]
            q_rank = old["quality_rank"]
        elif old_state in _ADVANCED_STATES:
            new_state = old_state
            res_id = old["resource_id"]
            q_rank = old["quality_rank"]
        else:
            new_state = "wanted"
            res_id = None
            q_rank = None
        upserts.append((subscription_id, season, episode, new_state, res_id, q_rank, now))

    unexpected = [(s, e) for (s, e) in existing if (s, e) not in expected_keys]

    with db() as conn:
        for row in upserts:
            conn.execute(
                """
                INSERT INTO subscription_episode_states
                    (subscription_id, season, episode, state, resource_id, quality_rank, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subscription_id, season, episode) DO UPDATE SET
                    state = excluded.state,
                    resource_id = excluded.resource_id,
                    quality_rank = excluded.quality_rank,
                    updated_at = excluded.updated_at
                """,
                row,
            )
        for season, episode in unexpected:
            conn.execute(
                "DELETE FROM subscription_episode_states WHERE subscription_id = ? AND season = ? AND episode = ?",
                (subscription_id, season, episode),
            )


def _set_state(
    subscription_id: int,
    season: int,
    episode: int,
    state: str,
    *,
    resource_id: int | None = None,
    quality_rank: float | None = None,
) -> None:
    now = utc_now()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO subscription_episode_states
                (subscription_id, season, episode, state, resource_id, quality_rank, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(subscription_id, season, episode) DO UPDATE SET
                state = excluded.state,
                resource_id = COALESCE(excluded.resource_id, subscription_episode_states.resource_id),
                quality_rank = COALESCE(excluded.quality_rank, subscription_episode_states.quality_rank),
                updated_at = excluded.updated_at
            """,
            (subscription_id, season, episode, state, resource_id, quality_rank, now),
        )


def mark_matched(
    subscription_id: int,
    episode_key: tuple[int, int] | None,
    *,
    resource_id: int | None = None,
    quality_rank: float | None = None,
) -> None:
    """Record that a resource matched this episode (pre-delivery)."""
    if not episode_key:
        return
    _set_state(subscription_id, episode_key[0], episode_key[1], "matched", resource_id=resource_id, quality_rank=quality_rank)


def mark_delivered(
    subscription_id: int,
    episode_key: tuple[int, int] | None,
    *,
    resource_id: int | None = None,
    quality_rank: float | None = None,
) -> None:
    """Record that the matched resource was delivered to 115."""
    if not episode_key:
        return
    _set_state(subscription_id, episode_key[0], episode_key[1], "delivered", resource_id=resource_id, quality_rank=quality_rank)


def mark_in_library(
    subscription_id: int,
    episode_key: tuple[int, int] | None,
    *,
    resource_id: int | None = None,
    quality_rank: float | None = None,
) -> None:
    """Set an episode as present in Emby (called from the M3 webhook path)."""
    if not episode_key:
        return
    _set_state(subscription_id, episode_key[0], episode_key[1], "in_library", resource_id=resource_id, quality_rank=quality_rank)


def mark_upgraded(
    subscription_id: int,
    episode_key: tuple[int, int] | None,
    *,
    resource_id: int | None = None,
    quality_rank: float | None = None,
) -> None:
    """Mark a higher-quality version superseding the delivered one (M4)."""
    if not episode_key:
        return
    _set_state(subscription_id, episode_key[0], episode_key[1], "upgraded", resource_id=resource_id, quality_rank=quality_rank)


def mark_searching(subscription_id: int, episode_key: tuple[int, int] | None) -> None:
    """Flag an in-flight search for this episode (optional telemetry)."""
    if not episode_key:
        return
    _set_state(subscription_id, episode_key[0], episode_key[1], "searching")


def episode_states_for(subscription_id: int) -> list[dict[str, Any]]:
    """Return all per-episode rows ordered by season/episode for the frontend."""
    with db() as conn:
        rows = conn.execute(
            "SELECT season, episode, state, resource_id, quality_rank, updated_at "
            "FROM subscription_episode_states WHERE subscription_id = ? ORDER BY season, episode",
            (subscription_id,),
        ).fetchall()
    return [row_to_dict(r) for r in rows]


def missing_count(subscription_id: int) -> int:
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM subscription_episode_states "
            "WHERE subscription_id = ? AND state = 'wanted'",
            (subscription_id,),
        ).fetchone()
    return int(row["c"]) if row else 0


def completion_state(subscription: dict[str, Any]) -> dict[str, Any]:
    """Derive an aggregate progress view for the subscription (UI / automation)."""
    if subscription.get("media_type") != "tv":
        in_library = bool(subscription.get("in_library"))
        return {
            "media_type": "movie",
            "state": "complete" if in_library else "wanted",
            "expected": 1,
            "in_library": 1 if in_library else 0,
            "missing": 0 if in_library else 1,
        }

    sub_id = int(subscription["id"])
    states = episode_states_for(sub_id)
    expected = len(states)
    in_library = sum(1 for s in states if s["state"] == "in_library")
    advanced = sum(1 for s in states if s["state"] in ("matched", "delivered", "upgraded"))

    if expected == 0:
        snap = subscription_episode_snapshot(subscription)
        expected = int(snap.get("expected_count", 0))
        in_library = int(snap.get("owned_count", 0))
        if expected and in_library >= expected:
            state = "complete"
        elif advanced > 0:
            state = "partial"
        elif in_library > 0:
            state = "partial"
        else:
            state = "wanted"
        return {
            "media_type": "tv",
            "state": state,
            "expected": expected,
            "in_library": in_library,
            "missing": max(0, expected - in_library),
        }

    missing = expected - in_library
    if expected and in_library >= expected:
        state = "complete"
    elif advanced > 0 or in_library > 0:
        state = "partial"
    else:
        state = "wanted"
    return {
        "media_type": "tv",
        "state": state,
        "expected": expected,
        "in_library": in_library,
        "missing": missing,
    }
