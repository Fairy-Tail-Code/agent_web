"""
Tests for login security module.

Uses temp SQLite databases to test login counting, locking, and CAPTCHA.
"""

import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock


class TestLoginSecurity(unittest.TestCase):
    """Test LoginSecurity class."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_login.db")
        self.env_patcher = patch.dict(os.environ, {
            "DATA_DB_PATH": self.db_path,
            "LOGIN_SECURITY_ENABLED": "true",
        })
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_security(self, max_attempts=3, lockout_minutes=5):
        from auth.login_security import LoginSecurity
        return LoginSecurity(max_attempts=max_attempts, lockout_minutes=lockout_minutes)

    def test_initial_check_allows(self):
        """Initially, login should be allowed."""
        sec = self._make_security()
        result = sec.check("user@test.com", "127.0.0.1")
        self.assertTrue(result.allowed)
        self.assertEqual(result.remaining_attempts, 3)

    def test_record_failure_decrements_remaining(self):
        """After failures, remaining attempts decrease."""
        sec = self._make_security(max_attempts=3)
        sec.record_failure("user@test.com", "127.0.0.1")

        result = sec.check("user@test.com", "127.0.0.1")
        self.assertTrue(result.allowed)
        self.assertEqual(result.remaining_attempts, 2)

    def test_lockout_after_max_failures(self):
        """After max failures, account is locked."""
        sec = self._make_security(max_attempts=3)

        for _ in range(3):
            sec.record_failure("user@test.com", "127.0.0.1")

        result = sec.check("user@test.com", "127.0.0.1")
        self.assertFalse(result.allowed)
        self.assertIn("锁定", result.reason)

    def test_success_resets_counter(self):
        """Successful login resets failure counter."""
        sec = self._make_security(max_attempts=3)

        sec.record_failure("user@test.com", "127.0.0.1")
        sec.record_failure("user@test.com", "127.0.0.1")
        sec.record_success("user@test.com", "127.0.0.1")

        result = sec.check("user@test.com", "127.0.0.1")
        self.assertTrue(result.allowed)
        self.assertEqual(result.remaining_attempts, 3)

    def test_different_emails_independent(self):
        """Different emails (with different IPs) have independent counters."""
        sec = self._make_security(max_attempts=2)

        sec.record_failure("user1@test.com", "192.168.1.1")
        sec.record_failure("user1@test.com", "192.168.1.1")

        # user1 is locked (email + IP both locked)
        result1 = sec.check("user1@test.com", "192.168.1.1")
        self.assertFalse(result1.allowed)

        # user2 at different IP is still allowed
        result2 = sec.check("user2@test.com", "192.168.1.2")
        self.assertTrue(result2.allowed)

    def test_ip_lockout(self):
        """IP-based lockout works independently."""
        sec = self._make_security(max_attempts=2)

        sec.record_failure("user1@test.com", "192.168.1.1")
        sec.record_failure("user1@test.com", "192.168.1.1")

        # Same IP with different email should also be blocked
        result = sec.check("user2@test.com", "192.168.1.1")
        self.assertFalse(result.allowed)

    def test_security_disabled(self):
        """When disabled, all attempts are allowed."""
        from auth.login_security import LoginSecurity
        sec = LoginSecurity(max_attempts=2, enabled=False)

        for _ in range(10):
            sec.record_failure("user@test.com", "127.0.0.1")

        result = sec.check("user@test.com", "127.0.0.1")
        self.assertTrue(result.allowed)


class TestLoginLogs(unittest.TestCase):
    """Test login log recording."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_logs.db")
        self.env_patcher = patch.dict(os.environ, {
            "DATA_DB_PATH": self.db_path,
        })
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_record_success_log(self):
        from auth.login_logs import record_login_log, ensure_login_logs_table
        ensure_login_logs_table()

        log_id = record_login_log(
            email="user@test.com",
            ip="127.0.0.1",
            success=True,
        )
        self.assertTrue(log_id)

        # Verify in DB
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT email, success FROM auth_login_logs WHERE log_id = ?", (log_id,))
        row = cursor.fetchone()
        conn.close()

        self.assertEqual(row[0], "user@test.com")
        self.assertEqual(row[1], 1)

    def test_record_failure_log(self):
        from auth.login_logs import record_login_log, ensure_login_logs_table
        ensure_login_logs_table()

        log_id = record_login_log(
            email="user@test.com",
            ip="127.0.0.1",
            success=False,
            failure_reason="wrong_password",
        )
        self.assertTrue(log_id)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT success, failure_reason FROM auth_login_logs WHERE log_id = ?", (log_id,))
        row = cursor.fetchone()
        conn.close()

        self.assertEqual(row[0], 0)
        self.assertEqual(row[1], "wrong_password")


class TestCaptcha(unittest.TestCase):
    """Test CAPTCHA verification."""

    def test_disabled_allows_all(self):
        """When CAPTCHA is disabled, all tokens pass."""
        with patch.dict(os.environ, {"CAPTCHA_ENABLED": "false"}):
            # Need to reimport to pick up new env
            import importlib
            import auth.captcha as captcha_mod
            importlib.reload(captcha_mod)

            import asyncio
            result = asyncio.run(captcha_mod.verify_turnstile(""))
            self.assertTrue(result)

    def test_no_secret_key_allows(self):
        """When secret key is not configured, tokens are accepted."""
        with patch.dict(os.environ, {"CAPTCHA_ENABLED": "true", "TURNSTILE_SECRET_KEY": ""}):
            import importlib
            import auth.captcha as captcha_mod
            importlib.reload(captcha_mod)

            import asyncio
            result = asyncio.run(captcha_mod.verify_turnstile("some_token"))
            self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
