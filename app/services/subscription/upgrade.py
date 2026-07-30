"""Quality upgrade window (M4) for ToGo115 subscriptions.

Once a resource is delivered for a subscription that has ``upgrade_window_days > 0``,
a "chase better quality" window opens. Inside that window, if a newer resource with a
higher :func:`quality_rank` matches the same scope (an episode for TV, the whole movie
for movies), the older delivered resource is marked ``superseded_by`` the new one and
the M1 per-episode state machine is advanced to ``upgraded``.

The check is triggered from the single delivery-success path
(``delivery/state._update_resource_delivery_status``) so we never supersede before the
replacement resource is actually delivered. The window is measured from the older
resource's ``delivered_at`` timestamp.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db import json_dumps, utc_now
from app.services.subscription.episode.parser import episode_keys_from_text_for_subscription
from app.services.subscription.match.quality import _text_contains_any


# Minimum rank delta required to treat a newer resource as a genuine upgrade.
_RANK_DELTA = 2.0

_RESOLUTION_RE = re.compile(r"(?i)\b(2160p|2160|4k|1080p|1080|720p|720|480p|sd)\b")
_RES_SCORE = {
    "2160": 40.0,
    "2160p": 40.0,
    "4k": 40.0,
    "1080": 30.0,
    "1080p": 30.0,
    "720": 20.0,
    "720p": 20.0,
    "480p": 10.0,
    "sd": 10.0,
}
# Ordered most-preferred first; first hit wins the source bonus.
_SOURCE_SCORE = [
    (["remux"], 15.0),
    (["web-dl", "webdl", "web dl"], 12.0),
    (["bluray", "bdrip", "bdrrip", "brrip"], 10.0),
    (["hdtv"], 5.0),
]
_PENALTY_TOKENS = ["cam", "telesync", "tsrip", "ts rip", "hc", "screener", "ppv"]


def quality_rank(text: str) -> float:
    """Normalized quality score from a resource title/message text.

    Combines resolution, source/encode, and penalties into a single comparable
    float. Higher is better. Two resources of the same nominal resolution but
    different encode (e.g. 1080p WEB-DL vs 1080p Remux) get different scores so the
    upgrade window can prefer the better one.
    """
    if not text:
        return 0.0
    raw = text.casefold()
    score = 10.0
    match = _RESOLUTION_RE.search(text)
    if match:
        score += _RES_SCORE.get(match.group(1).casefold(), 0.0)
    for tokens, bonus in _SOURCE_SCORE:
        if _text_contains_any(raw, tokens):
            score += bonus
            break
    if _text_contains_any(raw, _PENALTY_TOKENS):
        score -= 20.0
    return round(score, 1)


def _episodes_for_text(subscription: dict[str, Any], text: str) -> set[tuple[int, int]]:
    if str(subscription.get("media_type") or "") != "tv":
        return set()
    try:
        return episode_keys_from_text_for_subscription(subscription, text)
    except Exception:
        return set()


def _within_window(delivered_at: str | None, window_days: int, now: datetime) -> bool:
    if not delivered_at:
        return False
    try:
        dt = datetime.fromisoformat(delivered_at)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt + timedelta(days=window_days) >= now


def maybe_upgrade(conn: Any, resource_id: int) -> bool:
    """Supersede older, lower-quality delivered resources with this one (M4).

    Must be called after ``resource_id`` is marked ``delivered`` (so the caller
    already committed/is committing that status on ``conn``). Returns True if at
    least one older resource was superseded.
    """
    row = conn.execute(
        "SELECT id, subscription_id, title, status, quality_rank, superseded_by "
        "FROM resources WHERE id = ?",
        (resource_id,),
    ).fetchone()
    if not row:
        return False
    if row["superseded_by"] is not None:
        return False
    if str(row["status"] or "") != "delivered":
        return False

    # Read the subscription on the same connection (no nested transaction) to avoid
    # SQLite lock contention while the delivery write txn is still open.
    sub = conn.execute(
        "SELECT id, media_type, tmdb_seasons, emby_episode_keys, emby_count, tmdb_total_count, upgrade_window_days "
        "FROM subscriptions WHERE id = ?",
        (int(row["subscription_id"]),),
    ).fetchone()
    if not sub:
        return False
    subscription = dict(sub)
    window_days = int(subscription.get("upgrade_window_days") or 0)
    if window_days <= 0:
        return False

    text = str(row["title"] or "")
    new_rank = quality_rank(text)
    media_type = str(subscription.get("media_type") or "")
    new_episodes = _episodes_for_text(subscription, text)
    now = datetime.now(timezone.utc)

    existing = conn.execute(
        "SELECT id, title, quality_rank, delivered_at FROM resources "
        "WHERE subscription_id = ? AND id != ? AND status = 'delivered' AND superseded_by IS NULL",
        (int(row["subscription_id"]), resource_id),
    ).fetchall()

    upgraded = False
    for ex in existing:
        old_rank = ex["quality_rank"]
        if old_rank is None:
            continue
        if old_rank + _RANK_DELTA >= new_rank:
            continue
        if not _within_window(ex["delivered_at"], window_days, now):
            continue
        ex_episodes = _episodes_for_text(subscription, ex["title"])
        if media_type == "tv":
            overlap = ex_episodes & new_episodes
            if not overlap:
                continue
        else:
            overlap = None
        conn.execute(
            "UPDATE resources SET superseded_by = ?, updated_at = ? WHERE id = ?",
            (resource_id, utc_now(), ex["id"]),
        )
        if media_type == "tv" and overlap:
            # Write the M1 "upgraded" state on the same connection (no nested txn)
            # to avoid SQLite "database is locked" under the delivery transaction.
            for season, episode in overlap:
                conn.execute(
                    """
                    INSERT INTO subscription_episode_states
                        (subscription_id, season, episode, state, resource_id, quality_rank, updated_at)
                    VALUES (?, ?, ?, 'upgraded', ?, ?, ?)
                    ON CONFLICT(subscription_id, season, episode) DO UPDATE SET
                        state = 'upgraded',
                        resource_id = COALESCE(?, subscription_episode_states.resource_id),
                        quality_rank = COALESCE(?, subscription_episode_states.quality_rank),
                        updated_at = ?
                    """,
                    (int(row["subscription_id"]), season, episode, resource_id, new_rank, now.isoformat(),
                     resource_id, new_rank, now.isoformat()),
                )
        upgraded = True
        try:
            conn.execute(
                "INSERT INTO logs (level, scope, message, payload, created_at) "
                "VALUES ('info', 'subscription', ?, ?, ?)",
                (
                    "洗版期：更高画质资源已取代旧资源",
                    json_dumps(
                        {
                            "subscription_id": int(row["subscription_id"]),
                            "new_resource_id": resource_id,
                            "superseded_resource_id": ex["id"],
                            "old_rank": old_rank,
                            "new_rank": new_rank,
                        }
                    ),
                    utc_now(),
                ),
            )
        except Exception:
            # Logging must never break the upgrade write.
            pass

    # Record this resource's own quality score + delivery time for future comparisons.
    conn.execute(
        "UPDATE resources SET quality_rank = ?, delivered_at = ? WHERE id = ?",
        (new_rank, now.isoformat(), resource_id),
    )
    return upgraded
