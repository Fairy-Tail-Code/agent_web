"""
登录日志记录

使用 SQLite 存储登录日志，记录 IP、时间、结果等信息。
"""

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


# === 建表 SQL ===

_CREATE_LOGIN_LOGS_TABLE = """
CREATE TABLE IF NOT EXISTS auth_login_logs (
    log_id         TEXT PRIMARY KEY,
    email          TEXT NOT NULL,
    ip             TEXT NOT NULL,
    user_agent     TEXT,
    success        INTEGER NOT NULL DEFAULT 0,
    failure_reason TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_logs_email ON auth_login_logs(email);
CREATE INDEX IF NOT EXISTS idx_login_logs_ip ON auth_login_logs(ip);
CREATE INDEX IF NOT EXISTS idx_login_logs_created_at ON auth_login_logs(created_at);
"""


def _get_db_path() -> str:
    return os.getenv("DATA_DB_PATH", "./user_cache/data/data.db")


def ensure_login_logs_table() -> None:
    """确保 auth_login_logs 表存在"""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_CREATE_LOGIN_LOGS_TABLE)
        conn.commit()
    finally:
        conn.close()


def record_login_log(
    email: str,
    ip: str,
    success: bool,
    user_agent: Optional[str] = None,
    failure_reason: Optional[str] = None,
) -> str:
    """
    记录一条登录日志。

    Args:
        email: 登录邮箱
        ip: 请求 IP
        success: 是否成功
        user_agent: 浏览器 UA
        failure_reason: 失败原因

    Returns:
        log_id
    """
    db_path = _get_db_path()
    log_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO auth_login_logs (log_id, email, ip, user_agent, success, failure_reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (log_id, email, ip, user_agent, 1 if success else 0, failure_reason, now),
        )
        conn.commit()
    finally:
        conn.close()

    return log_id
