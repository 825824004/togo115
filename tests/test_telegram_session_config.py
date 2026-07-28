from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.adapters.telegram.session.config import (
    TELEGRAM_CLIENT_INIT_FAILURE_COOLDOWN_SECONDS,
    TELEGRAM_SESSION_BUSY_TIMEOUT_MS,
    BusyTimeoutSQLiteSession,
    TelegramSessionConfigMixin,
)
from app.services.adapters.telegram.session.client_errors import client_error_message
from app.services.adapters.telegram.session.login import TelegramLoginMixin, TELEGRAM_SESSION_DUPLICATED_MESSAGE


class TelegramSessionConfigTest(unittest.TestCase):
    def test_telegram_session_enables_busy_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = BusyTimeoutSQLiteSession(str(Path(tmp) / "telegram_user"))
            try:
                cursor = session._cursor()
                busy_timeout = cursor.execute("PRAGMA busy_timeout").fetchone()[0]
                journal_mode = cursor.execute("PRAGMA journal_mode").fetchone()[0]
                cursor.close()
            finally:
                session.close()

        self.assertEqual(busy_timeout, TELEGRAM_SESSION_BUSY_TIMEOUT_MS)
        self.assertEqual(str(journal_mode).casefold(), "wal")

    def test_client_init_lock_does_not_shadow_method(self) -> None:
        mixin = TelegramSessionConfigMixin()
        first = mixin._get_client_init_lock(object())
        second = mixin._get_client_init_lock(object())

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertTrue(callable(mixin._get_client_init_lock))

    def test_classifies_initialization_errors(self) -> None:
        mixin = TelegramSessionConfigMixin()

        cases = [
            (sqlite3.OperationalError("database is locked"), "session-locked"),
            (sqlite3.DatabaseError("file is not a database"), "session-corrupt"),
            (asyncio.TimeoutError(), "timeout"),
            (OSError("Connection refused by proxy"), "network-or-proxy"),
            (RuntimeError("Telegram API ID/API HASH 尚未配置"), "missing-config"),
            (RuntimeError("Auth key unregistered"), "auth"),
            (
                RuntimeError(
                    "The authorization key (session file) was used under two different IP addresses simultaneously"
                ),
                "session-duplicated",
            ),
        ]

        for exc, category in cases:
            with self.subTest(category=category):
                self.assertEqual(mixin._classify_client_error(exc), category)

    def test_empty_timeout_error_has_friendly_message(self) -> None:
        self.assertIn("连接 Telegram 超时", client_error_message("timeout", asyncio.TimeoutError()))

    def test_config_status_contains_session_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            class LocalMixin(TelegramSessionConfigMixin):
                def _session_path(self) -> Path:
                    return Path(tmp) / "telegram_user"

            session_file = Path(tmp) / "telegram_user.session"
            session_file.write_text("session", encoding="utf-8")
            with patch("app.services.adapters.telegram.session.config.get_setting", return_value={"api_id": "1", "api_hash": "hash"}):
                status = LocalMixin()._telegram_config_status()

        self.assertEqual(status["api_id"], True)
        self.assertEqual(status["api_hash"], True)
        self.assertEqual(status["session_file"], True)
        self.assertTrue(str(status["session_path"]).endswith("telegram_user.session"))

    def test_quarantine_corrupt_session_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            class LocalMixin(TelegramSessionConfigMixin):
                def _session_path(self) -> Path:
                    return Path(tmp) / "telegram_user"

            session_file = Path(tmp) / "telegram_user.session"
            wal_file = Path(str(session_file) + "-wal")
            session_file.write_text("broken", encoding="utf-8")
            wal_file.write_text("wal", encoding="utf-8")

            quarantined = LocalMixin()._quarantine_session_file()

            self.assertIsNotNone(quarantined)
            self.assertFalse(session_file.exists())
            self.assertTrue(Path(quarantined).exists())
            self.assertTrue(Path(str(quarantined) + "-wal").exists())


class TelegramLoginSessionRecoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_qr_login_quarantines_duplicated_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            class LocalMixin(TelegramLoginMixin, TelegramSessionConfigMixin):
                async def client(self):
                    raise RuntimeError(
                        "The authorization key (session file) was used under two different IP addresses simultaneously"
                    )

                def _session_path(self) -> Path:
                    return Path(tmp) / "telegram_user"

            session_file = Path(tmp) / "telegram_user.session"
            session_file.write_text("session", encoding="utf-8")

            with patch("app.services.adapters.telegram.session.login.save_flow") as save_flow:
                with self.assertRaisesRegex(RuntimeError, "Telegram 会话已被判定"):
                    await LocalMixin().qr_login_start()

            self.assertFalse(session_file.exists())
            self.assertIn(TELEGRAM_SESSION_DUPLICATED_MESSAGE, str(save_flow.call_args.args[1]["error"]))

    async def test_client_init_timeout_enters_short_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            class LocalMixin(TelegramSessionConfigMixin):
                _client = None
                _client_loop = None
                _client_init_failure = None

                def _config(self) -> dict:
                    return {"api_id": "1", "api_hash": "hash"}

                def _session_path(self) -> Path:
                    return Path(tmp) / "telegram_user"

                async def _connect_client_with_retry(self, config, proxy):
                    raise asyncio.TimeoutError()

            with patch("app.services.adapters.telegram.session.client.module_proxy", return_value=None):
                with self.assertRaises(asyncio.TimeoutError):
                    await LocalMixin().client()
                with self.assertRaisesRegex(RuntimeError, "暂缓重复初始化"):
                    await LocalMixin().client()

            failure = LocalMixin._client_init_failure
            self.assertIsNotNone(failure)
            self.assertLessEqual(float(failure["until"]), __import__("time").monotonic() + TELEGRAM_CLIENT_INIT_FAILURE_COOLDOWN_SECONDS)

