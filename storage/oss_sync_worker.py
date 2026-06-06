"""
后台 OSS 归档 Worker

扫描 storage_files 表中 status='local' 的文件，异步上传到 OSS。
支持本地文件清理：同步成功后可选删除本地副本，定期清理超过保留期的本地文件。

使用方式：
- 集成到主应用 lifespan（推荐）
- 作为独立进程启动: python -m storage.oss_sync_worker

环境变量：
  OSS_ENABLED              启用 OSS 开关（默认 false）
  DATA_DB_PATH             SQLite 数据库路径
  OSS_CLEANUP_LOCAL        同步后是否清理本地文件（默认 true）
  OSS_LOCAL_RETENTION_DAYS 本地文件保留天数（默认 7 天）
  OSS_SYNC_INTERVAL        Worker 轮询间隔秒数（默认 120）
"""

import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from agno.utils.log import logger


class OssSyncWorker:
    """
    后台 Worker：扫描未归档文件，异步上传 OSS，可选清理本地副本。
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        self.db_path = db_path or os.getenv("DATA_DB_PATH")
        if not self.db_path:
            raise RuntimeError("DATA_DB_PATH 未设置")

        self._stop_event = stop_event or threading.Event()

        # 从环境变量读取清理策略配置
        self.cleanup_local_after_sync = os.getenv(
            "OSS_CLEANUP_LOCAL", "true"
        ).lower() in {"true", "1", "yes", "on"}

        self.local_retention_days = int(
            os.getenv("OSS_LOCAL_RETENTION_DAYS", "7")
        )

    # ── 生命周期控制 ──────────────────────────────────────────

    def request_stop(self) -> None:
        """请求 Worker 优雅停止。"""
        self._stop_event.set()

    @property
    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    # ── 数据库操作 ────────────────────────────────────────────

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)  # ty:ignore[invalid-argument-type]

    def get_pending_files(self, limit: int = 100) -> List[Tuple[str, str, str, str, str]]:
        """获取待同步文件（status='local' 且 oss_url 为空）。"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT file_id, user_id, module, filename, local_path
                FROM storage_files
                WHERE status = 'local' AND oss_url IS NULL
                ORDER BY created_at ASC
                LIMIT ?
            """, (limit,))
            return cursor.fetchall()
        finally:
            conn.close()

    def update_status(self, file_id: str, status: str, oss_url: Optional[str] = None):
        """更新文件状态。"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            if oss_url:
                cursor.execute("""
                    UPDATE storage_files
                    SET status = ?, oss_url = ?, updated_at = ?
                    WHERE file_id = ?
                """, (status, oss_url, now, file_id))
            else:
                cursor.execute("""
                    UPDATE storage_files
                    SET status = ?, updated_at = ?
                    WHERE file_id = ?
                """, (status, now, file_id))
            conn.commit()
        finally:
            conn.close()

    # ── 文件同步 ──────────────────────────────────────────────

    def sync_file(self, file_id: str, user_id: str, module: str, filename: str, local_path: str) -> Optional[str]:
        """
        同步单个文件到 OSS。同步成功后可选清理本地文件。

        Returns:
            OSS URL 或 None（失败时）。
        """
        from storage.file_manager import is_oss_enabled

        if not is_oss_enabled():
            return None

        if not os.path.exists(local_path):
            logger.warning(f"本地文件不存在，跳过: {local_path}")
            self.update_status(file_id, "sync_failed")
            return None

        # 获取对应 FileManager
        fm = self._get_file_manager(module)
        if fm is None:
            return None

        try:
            oss_url = fm.sync_to_oss(user_id, filename)
            self.update_status(file_id, "synced", oss_url)
            logger.info(f"OSS 同步成功: module={module} filename={filename}")

            # 同步成功后清理本地文件
            if self.cleanup_local_after_sync:
                self._remove_local_file(local_path)

            return oss_url
        except Exception as e:
            self.update_status(file_id, "sync_failed")
            logger.error(f"OSS 同步失败: module={module} filename={filename} error={e}")
            return None

    def run_once(self, limit: int = 100) -> int:
        """
        执行一轮同步。

        Returns:
            成功同步的文件数。
        """
        pending = self.get_pending_files(limit)
        if not pending:
            return 0

        logger.info(f"OSS Worker: 发现 {len(pending)} 个待同步文件")
        synced = 0
        for file_id, user_id, module, filename, local_path in pending:
            if self.is_stopped:
                break
            self.update_status(file_id, "syncing")
            result = self.sync_file(file_id, user_id, module, filename, local_path)
            if result:
                synced += 1
        return synced

    # ── 本地文件清理 ──────────────────────────────────────────

    def cleanup_old_local_files(self, limit: int = 200) -> int:
        """
        清理已同步到 OSS 且超过本地保留期的文件。

        扫描 storage_files 中 status='synced' 且 updated_at 早于
        local_retention_days 前的记录，删除对应的本地文件。

        Returns:
            本次清理的文件数。
        """
        if self.local_retention_days <= 0:
            return 0

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.local_retention_days)
        ).isoformat()

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT file_id, local_path, module, filename
                FROM storage_files
                WHERE status = 'synced'
                  AND oss_url IS NOT NULL
                  AND updated_at < ?
                LIMIT ?
            """, (cutoff, limit))
            rows = cursor.fetchall()
        finally:
            conn.close()

        cleaned = 0
        for file_id, local_path, module, filename in rows:
            if self.is_stopped:
                break
            if not local_path or not os.path.exists(local_path):
                continue
            if self._remove_local_file(local_path):
                cleaned += 1

        return cleaned

    # ── 主循环 ────────────────────────────────────────────────

    def run_forever(self, interval_seconds: Optional[int] = None) -> None:
        """
        持续运行，定时扫描同步 + 清理。

        Args:
            interval_seconds: 轮询间隔，默认读取 OSS_SYNC_INTERVAL 环境变量或 120s。
        """
        if interval_seconds is None:
            interval_seconds = int(os.getenv("OSS_SYNC_INTERVAL", "120"))

        logger.info(
            f"OSS Worker 启动: 间隔 {interval_seconds}s, "
            f"同步后清理={self.cleanup_local_after_sync}, "
            f"本地保留={self.local_retention_days}天"
        )

        while not self._stop_event.is_set():
            try:
                synced = self.run_once()
                if synced:
                    logger.info(f"OSS Worker: 本轮同步 {synced} 个文件")

                cleaned = self.cleanup_old_local_files()
                if cleaned:
                    logger.info(f"OSS Worker: 本轮清理 {cleaned} 个过期本地文件")

            except Exception as e:
                logger.error(f"OSS Worker 异常: {e}")

            # 使用 Event.wait 替代 time.sleep，支持优雅中断
            self._stop_event.wait(interval_seconds)

        logger.info("OSS Worker 已停止")

    # ── 内部工具 ──────────────────────────────────────────────

    @staticmethod
    def _get_file_manager(module: str):
        """按模块名获取对应的 FileManager 实例。"""
        if module == "data":
            from storage.file_manager import DataFileManager
            return DataFileManager()
        elif module == "office":
            from storage.file_manager import OfficeFileManager
            return OfficeFileManager()
        elif module == "knowledge":
            from storage.file_manager import KnowledgeFileManager
            return KnowledgeFileManager()
        else:
            logger.warning(f"未知模块: {module}，跳过")
            return None

    @staticmethod
    def _remove_local_file(local_path: str) -> bool:
        """安全删除本地文件，返回是否成功。"""
        try:
            os.remove(local_path)
            logger.info(f"已清理本地文件: {local_path}")
            return True
        except Exception as e:
            logger.warning(f"清理本地文件失败: {local_path}, error={e}")
            return False


if __name__ == "__main__":
    worker = OssSyncWorker()
    worker.run_forever()
