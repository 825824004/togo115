from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings
from app.db import db, init_db
from app.services.subscription.crud.rows import get_subscription
from app.services.subscription.upgrade import (
    close_expired_upgrade_windows,
    maybe_upgrade,
    quality_rank,
)


def _iso(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


class UpgradeWindowCloseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        self.old_database_path = settings.database_path
        settings.data_dir = Path(self.temp_dir.name)
        settings.database_path = settings.data_dir / "togo115-test.sqlite3"
        init_db()

    def tearDown(self) -> None:
        settings.data_dir = self.old_data_dir
        settings.database_path = self.old_database_path
        self.temp_dir.cleanup()

    def _insert_subscription(self, *, media_type: str = "movie", in_library: bool = False,
                             upgrade_window_days: int = 14, upgrade_closed_at=None,
                             tmdb_id: int | None = None) -> int:
        with db() as conn:
            return conn.execute(
                """
                INSERT INTO subscriptions
                    (title, media_type, keywords, delivery_mode, target_path,
                     in_library, upgrade_window_days, upgrade_closed_at,
                     tmdb_id, created_at, updated_at)
                VALUES
                    ('Test', ?, '["test"]', '115', '/t', ?, ?, ?, ?, ?, ?)
                """,
                (media_type, 1 if in_library else 0, upgrade_window_days,
                 upgrade_closed_at, tmdb_id, _iso(0), _iso(0)),
            ).lastrowid

    def _insert_resource(self, sub_id: int, *, title: str = "Test 1080p",
                        status: str = "delivered", delivered_at=None,
                        quality_rank=None, superseded_by=None, url: str | None = None) -> int:
        resource_url = url or f"https://115.com/s/{abs(hash(title))}"
        with db() as conn:
            return conn.execute(
                """
                INSERT INTO resources
                    (subscription_id, source, title, url, status,
                     delivered_at, quality_rank, superseded_by, created_at, updated_at)
                VALUES
                    (?, 'Manual', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sub_id, title, resource_url, status, delivered_at, quality_rank, superseded_by, _iso(0), _iso(0)),
            ).lastrowid

    def test_window_not_expired_is_not_closed(self):
        sub_id = self._insert_subscription(upgrade_window_days=14)
        self._insert_resource(sub_id, delivered_at=_iso(1 * 24 * 3600))  # 1 day ago
        closed = close_expired_upgrade_windows()
        self.assertEqual(closed, 0)
        self.assertIsNone(get_subscription(sub_id).get("upgrade_closed_at"))

    def test_window_expired_but_incomplete_stays_active(self):
        # Movie not yet in library -> completed state is "wanted", so only the window closes.
        sub_id = self._insert_subscription(upgrade_window_days=14, in_library=False)
        self._insert_resource(sub_id, delivered_at=_iso(20 * 24 * 3600))  # 20 days ago
        closed = close_expired_upgrade_windows()
        self.assertEqual(closed, 1)
        sub = get_subscription(sub_id)
        self.assertIsNotNone(sub.get("upgrade_closed_at"))
        self.assertEqual(sub["status"], "active")

    def test_window_expired_and_complete_soft_completes(self):
        # Movie already in library -> complete -> soft-completed (hidden, row kept).
        sub_id = self._insert_subscription(upgrade_window_days=14, in_library=True)
        self._insert_resource(sub_id, delivered_at=_iso(20 * 24 * 3600))
        closed = close_expired_upgrade_windows()
        self.assertEqual(closed, 1)
        sub = get_subscription(sub_id)
        self.assertIsNotNone(sub.get("upgrade_closed_at"))
        self.assertEqual(sub["status"], "completed")

    def test_no_window_subscriptions_ignored(self):
        sub_id = self._insert_subscription(upgrade_window_days=0)
        self._insert_resource(sub_id, delivered_at=_iso(20 * 24 * 3600))
        self.assertEqual(close_expired_upgrade_windows(), 0)

    def test_maybe_upgrade_bails_when_window_closed(self):
        # Once the upgrade window is closed, a higher-quality delivery must not supersede.
        sub_id = self._insert_subscription(upgrade_window_days=14, upgrade_closed_at=_iso(0))
        old_id = self._insert_resource(
            sub_id, title="Old 1080p WEB-DL", delivered_at=_iso(20 * 24 * 3600),
            quality_rank=quality_rank("Old 1080p WEB-DL"),
        )
        new_id = self._insert_resource(
            sub_id, title="New 2160p Remux", delivered_at=_iso(0),
            quality_rank=quality_rank("New 2160p Remux"),
        )
        with db() as conn:
            result = maybe_upgrade(conn, new_id)
        self.assertFalse(result)
        with db() as conn:
            old_superseded = conn.execute(
                "SELECT superseded_by FROM resources WHERE id = ?", (old_id,)
            ).fetchone()["superseded_by"]
        self.assertIsNone(old_superseded)


if __name__ == "__main__":
    unittest.main()
