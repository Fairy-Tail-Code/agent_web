"""
登录安全核心：登录失败计数 + 账号锁定

使用 SQLite 存储失败计数（轻量，无需 Redis 依赖）。
支持按 email 和 IP 分别计数。
"""

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class LoginAttemptResult:
    """登录尝试检查结果"""
    allowed: bool
    reason: Optional[str] = None  # None = 允许，string = 拒绝原因
    remaining_attempts: int = 0
    lockout_until: Optional[str] = None  # ISO format datetime


# === SQLite 建表 SQL ===

_CREATE_LOGIN_ATTEMPTS_TABLE = """
CREATE TABLE IF NOT EXISTS auth_login_attempts (
    key         TEXT PRIMARY KEY,
    fail_count  INTEGER DEFAULT 0,
    locked_until TEXT,
    updated_at  TEXT NOT NULL
);
"""

# === 配置 ===

MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
LOCKOUT_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))
SECURITY_ENABLED = os.getenv("LOGIN_SECURITY_ENABLED", "true").lower() == "true"


def _get_db_path() -> str:
    return os.getenv("DATA_DB_PATH", "./user_cache/data/data.db")


def _ensure_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_CREATE_LOGIN_ATTEMPTS_TABLE)
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LoginSecurity:
    """
    登录安全管理器。

    使用 SQLite 存储失败计数，支持：
    - 按 email 计数
    - 按 IP 计数
    - 锁定后自动过期
    """

    def __init__(
        self,
        max_attempts: int = MAX_ATTEMPTS,
        lockout_minutes: int = LOCKOUT_MINUTES,
        enabled: bool = SECURITY_ENABLED,
    ):
        self.max_attempts = max_attempts
        self.lockout_minutes = lockout_minutes
        self.enabled = enabled
        self._db_path = _get_db_path()
        _ensure_table(self._db_path)

    def check(self, email: str, ip: str) -> LoginAttemptResult:
        """
        检查是否允许尝试登录。

        Returns:
            LoginAttemptResult: allowed=True 可以尝试，allowed=False 被锁定
        """
        if not self.enabled:
            return LoginAttemptResult(allowed=True, remaining_attempts=self.max_attempts)

        # 检查 email 和 IP 两个维度
        for key_prefix in [f"email:{email}", f"ip:{ip}"]:
            result = self._check_key(key_prefix)
            if not result.allowed:
                return result

        # 计算剩余尝试次数（取较小值）
        email_remaining = self._get_remaining(f"email:{email}")
        ip_remaining = self._get_remaining(f"ip:{ip}")
        remaining = min(email_remaining, ip_remaining)

        return LoginAttemptResult(allowed=True, remaining_attempts=remaining)

    def record_failure(self, email: str, ip: str) -> None:
        """记录一次登录失败"""
        if not self.enabled:
            return

        for key in [f"email:{email}", f"ip:{ip}"]:
            self._increment_fail(key)

    def record_success(self, email: str, ip: str = "") -> None:
        """登录成功，清零计数"""
        if not self.enabled:
            return

        for key in [f"email:{email}", f"ip:{ip}"]:
            self._reset(key)

    def is_locked_out(self, email: str, ip: str) -> bool:
        """
        便捷方法：检查是否被锁定。

        Returns:
            True 表示已被锁定，False 表示可以继续尝试。
        """
        return not self.check(email, ip).allowed

    def _check_key(self, key: str) -> LoginAttemptResult:
        """检查单个 key 的锁定状态"""
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT fail_count, locked_until FROM auth_login_attempts WHERE key = ?",
                (key,),
            )
            row = cursor.fetchone()

            if not row:
                return LoginAttemptResult(allowed=True, remaining_attempts=self.max_attempts)

            fail_count, locked_until = row

            # 检查是否还在锁定期间
            if locked_until:
                locked_dt = datetime.fromisoformat(locked_until)
                now = datetime.now(timezone.utc)
                if now < locked_dt:
                    remaining_time = locked_dt - now
                    remaining_mins = int(remaining_time.total_seconds() / 60) + 1
                    return LoginAttemptResult(
                        allowed=False,
                        reason=f"账号已锁定，请 {remaining_mins} 分钟后再试",
                        remaining_attempts=0,
                        lockout_until=locked_until,
                    )
                # 锁定期已过，自动解除
                self._reset(key)
                return LoginAttemptResult(allowed=True, remaining_attempts=self.max_attempts)

            remaining = max(0, self.max_attempts - fail_count)
            return LoginAttemptResult(allowed=True, remaining_attempts=remaining)
        finally:
            conn.close()

    def _get_remaining(self, key: str) -> int:
        """获取剩余尝试次数"""
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT fail_count FROM auth_login_attempts WHERE key = ?",
                (key,),
            )
            row = cursor.fetchone()
            if not row:
                return self.max_attempts
            return max(0, self.max_attempts - row[0])
        finally:
            conn.close()

    def _increment_fail(self, key: str) -> None:
        """增加失败计数"""
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            now = _now_iso()
            cursor.execute(
                "INSERT INTO auth_login_attempts (key, fail_count, updated_at) VALUES (?, 1, ?) "
                "ON CONFLICT(key) DO UPDATE SET fail_count = fail_count + 1, updated_at = ?",
                (key, now, now),
            )

            # 检查是否达到锁定阈值
            cursor.execute(
                "SELECT fail_count FROM auth_login_attempts WHERE key = ?",
                (key,),
            )
            row = cursor.fetchone()
            if row and row[0] >= self.max_attempts:
                # 锁定
                from datetime import timedelta
                locked_until = (
                    datetime.now(timezone.utc) + timedelta(minutes=self.lockout_minutes)
                ).isoformat()
                cursor.execute(
                    "UPDATE auth_login_attempts SET locked_until = ? WHERE key = ?",
                    (locked_until, key),
                )

            conn.commit()
        finally:
            conn.close()

    def _reset(self, key: str) -> None:
        """重置计数"""
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM auth_login_attempts WHERE key = ?",
                (key,),
            )
            conn.commit()
        finally:
            conn.close()


# 模块级单例
_login_security: Optional[LoginSecurity] = None


def get_login_security() -> LoginSecurity:
    """获取 LoginSecurity 单例"""
    global _login_security
    if _login_security is None:
        _login_security = LoginSecurity()
    return _login_security
