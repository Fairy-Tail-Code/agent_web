"""
统一存储抽象层

为 Data、Office、Knowledge 三个模块提供统一的文件管理能力：
- 用户隔离的本地路径
- SQLite 元数据管理（storage.files 表）
- OSS 异步归档
"""

import os
import re
import shutil
import sqlite3
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from dotenv import load_dotenv
from agno.utils.log import logger

load_dotenv()


# === OSS 配置检查 ===

def is_oss_enabled() -> bool:
    """检查 OSS 是否真正可用（配置了 access_key 且启用了开关）"""
    if os.getenv("OSS_ENABLED", "false").lower() != "true":
        return False
    try:
        from storage import get_qiniu_storage
        storage = get_qiniu_storage()
        return bool(storage.config.access_key and storage.config.secret_key)
    except Exception:
        return False


# === 数据模型 ===

@dataclass
class FileMetadata:
    """文件元数据记录"""
    file_id: str
    user_id: str
    module: str
    filename: str
    local_path: str
    oss_url: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    status: str = "local"
    created_at: str = ""
    updated_at: str = ""


# === SQLite 建表 SQL ===

_CREATE_STORAGE_FILES_TABLE = """
CREATE TABLE IF NOT EXISTS storage_files (
    file_id      TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    module       TEXT NOT NULL,
    filename     TEXT NOT NULL,
    local_path   TEXT NOT NULL,
    oss_url      TEXT,
    file_size    BIGINT,
    mime_type    TEXT,
    status       TEXT DEFAULT 'local',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_storage_files_uk
    ON storage_files(user_id, module, filename);
CREATE INDEX IF NOT EXISTS idx_storage_files_user_id
    ON storage_files(user_id);
CREATE INDEX IF NOT EXISTS idx_storage_files_module
    ON storage_files(module);
CREATE INDEX IF NOT EXISTS idx_storage_files_status
    ON storage_files(status);
"""


def _ensure_storage_table(db_path: str) -> None:
    """确保 storage_files 表存在（幂等，首次访问时调用）"""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_CREATE_STORAGE_FILES_TABLE)
        conn.commit()
    finally:
        conn.close()


# === 基类 ===

class BaseFileManager(ABC):
    """
    所有文件管理器的基类。

    提供：
    - 用户目录隔离
    - SQLite 元数据管理
    - OSS 异步归档
    - 统一异常处理
    """

    # 子类必须定义
    module: str = ""

    def __init__(self):
        self._storage = None
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保 SQLite 元数据表已创建"""
        db_path = self._get_db_path()
        _ensure_storage_table(db_path)

    @property
    def storage(self):
        """延迟获取 OSS 存储实例"""
        if self._storage is None:
            try:
                from storage import get_qiniu_storage
                self._storage = get_qiniu_storage()
            except Exception:
                self._storage = None
        return self._storage

    @abstractmethod
    def get_base_dir(self, user_id: str) -> Path:
        """子类返回本地根目录（user_id="*" 表示模块根目录）"""

    @abstractmethod
    def get_module_prefix(self) -> str:
        """子类返回 OSS 路径前缀"""

    # === 工具方法 ===

    @staticmethod
    def safe_user_segment(user_id: str) -> str:
        """将 user_id 转为安全的目录名"""
        raw = str(user_id).strip()
        if not raw:
            return "anonymous"
        return "".join(
            ch if ch.isalnum() or ch in {"-", "_", "."} else "_"
            for ch in raw
        ).strip("._") or "anonymous"

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """清理文件名，移除不安全字符"""
        name = Path(filename).name or "unnamed"
        return re.sub(r"[^\w\-_. ]", "_", name)

    def _get_user_dir(self, user_id: str) -> Path:
        """获取用户专属目录（自动创建）"""
        base = self.get_base_dir("*")
        user_dir = base / self.safe_user_segment(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    @staticmethod
    def _get_db_path() -> str:
        """获取元数据库路径"""
        db_path = os.getenv("DATA_DB_PATH")
        if not db_path:
            raise RuntimeError("DATA_DB_PATH 未设置")
        return db_path

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self._get_db_path())

    # === 本地文件操作 ===

    def save_local(
        self,
        user_id: str,
        content: Union[bytes, Path],
        filename: str,
    ) -> str:
        """
        保存文件到本地用户隔离目录。

        Args:
            user_id: 用户 ID
            content: 文件内容 (bytes) 或源文件路径 (Path/str)
            filename: 目标文件名

        Returns:
            本地绝对路径
        """
        user_dir = self._get_user_dir(user_id)
        safe_filename = self.sanitize_filename(filename)
        dest_path = user_dir / safe_filename

        if isinstance(content, (str, Path)):
            # content 是源文件路径，复制过来
            shutil.copy2(str(content), str(dest_path))
        elif isinstance(content, bytes):
            # 原子写入：先写 .tmp 再 rename
            tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
            with open(tmp_path, "wb") as f:
                f.write(content)
            tmp_path.replace(dest_path)
        else:
            raise TypeError(f"content 类型不支持: {type(content)}")

        logger.info(f"文件已保存: user_id={user_id} module={self.module} path={dest_path}")
        return str(dest_path)

    def get_path(self, user_id: str, filename: Optional[str] = None) -> str:
        """
        获取本地路径（从 SQLite 查询最新记录）。

        Args:
            user_id: 用户 ID
            filename: 可选，指定文件名

        Returns:
            本地绝对路径

        Raises:
            FileNotFoundError: 未找到记录或本地文件不存在
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if filename:
                cursor.execute(
                    "SELECT local_path FROM storage_files "
                    "WHERE user_id = ? AND module = ? AND filename = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (user_id, self.module, filename),
                )
            else:
                cursor.execute(
                    "SELECT local_path FROM storage_files "
                    "WHERE user_id = ? AND module = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (user_id, self.module),
                )
            row = cursor.fetchone()
            if not row:
                raise FileNotFoundError(
                    f"未找到 user_id={user_id} module={self.module} 的文件记录"
                )
            path = row[0]
            if not os.path.exists(path):
                # 本地文件丢失，尝试 OSS 兜底
                oss_url = self._get_oss_url(user_id, filename)
                if oss_url:
                    logger.warning(f"本地文件丢失，从 OSS 恢复: {path}")
                    path = self._download_from_oss(oss_url, user_id, filename)
                else:
                    raise FileNotFoundError(f"本地文件不存在: {path}")
            return path
        finally:
            conn.close()

    def load(self, user_id: str, filename: Optional[str] = None) -> bytes:
        """加载文件内容"""
        path = self.get_path(user_id, filename)
        with open(path, "rb") as f:
            return f.read()

    # === SQLite 元数据操作 ===

    def register(
        self,
        user_id: str,
        local_path: str,
        filename: Optional[str] = None,
        file_size: Optional[int] = None,
        mime_type: Optional[str] = None,
    ) -> FileMetadata:
        """
        注册文件到 SQLite 元数据表。

        Args:
            user_id: 用户 ID
            local_path: 本地路径
            filename: 文件名（默认从路径推断）
            file_size: 文件大小
            mime_type: MIME 类型

        Returns:
            FileMetadata 对象
        """
        if filename is None:
            filename = Path(local_path).name

        now = datetime.now(timezone.utc).isoformat()
        file_id = str(uuid.uuid4())

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO storage_files
                (file_id, user_id, module, filename, local_path, file_size, mime_type, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'local', ?, ?)
                ON CONFLICT(user_id, module, filename) DO UPDATE SET
                    file_id = EXCLUDED.file_id,
                    local_path = EXCLUDED.local_path,
                    file_size = EXCLUDED.file_size,
                    mime_type = EXCLUDED.mime_type,
                    status = 'local',
                    oss_url = NULL,
                    updated_at = EXCLUDED.updated_at
            """, (file_id, user_id, self.module, filename, local_path, file_size, mime_type, now, now))
            conn.commit()
            logger.info(
                f"文件已注册: user_id={user_id} module={self.module} filename={filename}"
            )
        finally:
            conn.close()

        return FileMetadata(
            file_id=file_id,
            user_id=user_id,
            module=self.module,
            filename=filename,
            local_path=local_path,
            status="local",
            created_at=now,
            updated_at=now,
        )

    def _get_oss_url(self, user_id: str, filename: Optional[str] = None) -> Optional[str]:
        """从 SQLite 获取 OSS URL"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if filename:
                cursor.execute(
                    "SELECT oss_url FROM storage_files "
                    "WHERE user_id = ? AND module = ? AND filename = ? AND status = 'synced'",
                    (user_id, self.module, filename),
                )
            else:
                cursor.execute(
                    "SELECT oss_url FROM storage_files "
                    "WHERE user_id = ? AND module = ? AND status = 'synced' "
                    "ORDER BY created_at DESC LIMIT 1",
                    (user_id, self.module),
                )
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    # === OSS 操作 ===

    def _build_oss_key(self, user_id: str, filename: str) -> str:
        """构建 OSS key"""
        safe_user = self.safe_user_segment(user_id)
        safe_filename = self.sanitize_filename(filename)
        return f"{self.get_module_prefix()}/{safe_user}/{safe_filename}"

    def sync_to_oss(self, user_id: str, filename: Optional[str] = None) -> str:
        """
        同步文件到 OSS（同步阻塞）

        Args:
            user_id: 用户 ID
            filename: 可选，默认取最新的

        Returns:
            OSS URL
        """
        if not is_oss_enabled():
            raise RuntimeError("OSS 未启用")

        path = self.get_path(user_id, filename)
        filename = filename or Path(path).name

        if self.storage:
            oss_url = self.storage.upload_file(
                module=self.module,
                user_id=user_id,
                file_path=path,
                filename=filename,
            )
            self._update_status(user_id, filename, "synced", oss_url)
            return oss_url

        raise RuntimeError("OSS 存储未配置")

    def _update_status(self, user_id: str, filename: str, status: str, oss_url: Optional[str] = None):
        """更新文件状态"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            if oss_url:
                cursor.execute("""
                    UPDATE storage_files
                    SET status = ?, oss_url = ?, updated_at = ?
                    WHERE user_id = ? AND module = ? AND filename = ?
                """, (status, oss_url, now, user_id, self.module, filename))
            else:
                cursor.execute("""
                    UPDATE storage_files
                    SET status = ?, updated_at = ?
                    WHERE user_id = ? AND module = ? AND filename = ?
                """, (status, now, user_id, self.module, filename))
            conn.commit()
        finally:
            conn.close()

    def _download_from_oss(self, oss_url: str, user_id: str, filename: Optional[str] = None) -> str:
        """从 OSS 下载文件到本地（简单实现，后续可增强）"""
        import httpx

        user_dir = self._get_user_dir(user_id)
        fname = filename or "restored_file"
        dest = user_dir / self.sanitize_filename(fname)

        resp = httpx.get(oss_url, follow_redirects=True, timeout=60.0)
        resp.raise_for_status()

        with open(dest, "wb") as f:
            f.write(resp.content)

        logger.info(f"文件已从 OSS 恢复: {dest}")
        return str(dest)


# === 子类实现 ===

class DataFileManager(BaseFileManager):
    """Data 模块文件管理器"""

    module = "data"

    def get_base_dir(self, user_id: str) -> Path:
        base = Path(os.getenv("DATA_UPLOAD_DIR", "./user_cache/data"))
        if user_id == "*":
            return base
        return base / self.safe_user_segment(user_id)

    def get_module_prefix(self) -> str:
        return "data"

    def get_csv_path(self, user_id: str) -> str:
        """Data 专用：获取最新 CSV 路径（替代旧的 _get_data_path_by_user）"""
        return self.get_path(user_id, filename=None)

    def load_csv(self, user_id: str):
        """Data 专用：加载 CSV 为 DataFrame"""
        import pandas as pd
        path = self.get_path(user_id)
        return pd.read_csv(path)


class OfficeFileManager(BaseFileManager):
    """Office 模块文件管理器"""

    module = "office"

    def get_base_dir(self, user_id: str) -> Path:
        base = Path(os.getenv("OFFICE_BASE_DIR", "./user_cache/office"))
        if user_id == "*":
            return base
        return base / self.safe_user_segment(user_id)

    def get_module_prefix(self) -> str:
        return "office"

    def get_output_dir(self, user_id: str, format: str) -> Path:
        """
        Office 专用：获取输出目录

        Args:
            user_id: 用户 ID
            format: docx / pdf / md / search

        Returns:
            输出目录 Path
        """
        base = self.get_base_dir(user_id)
        output_dir = base / "output" / format.lower()
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def build_output_path(self, user_id: str, filename: str, format: str) -> str:
        """
        Office 专用：构建输出文件完整路径

        Args:
            user_id: 用户 ID
            filename: 文件名
            format: docx / pdf / md / search

        Returns:
            完整本地路径
        """
        output_dir = self.get_output_dir(user_id, format)
        safe_filename = self.sanitize_filename(filename)
        # 确保扩展名匹配格式
        ext = self._get_extension_for_format(format)
        if ext and not safe_filename.lower().endswith(ext):
            safe_filename = f"{safe_filename}{ext}"
        return str((output_dir / safe_filename).resolve())

    @staticmethod
    def _get_extension_for_format(format: str) -> str:
        mapping = {
            "docx": ".docx",
            "pdf": ".pdf",
            "md": ".md",
            "markdown": ".md",
            "search": ".json",
        }
        return mapping.get(format.lower(), "")


class KnowledgeFileManager(BaseFileManager):
    """知识库文件管理器"""

    module = "knowledge"

    def get_base_dir(self, user_id: str) -> Path:
        base = Path(os.getenv("KNOWLEDGE_BASE_DIR", "./user_cache/knowledge"))
        if user_id == "*":
            return base
        return base / self.safe_user_segment(user_id)

    def get_module_prefix(self) -> str:
        return "knowledge"
