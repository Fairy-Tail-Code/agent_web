"""
后台 OSS 归档 Worker

扫描 storage_files 表中 status='local' 的文件，异步上传到 OSS。

使用方式：
- 作为独立进程启动: python -m storage.oss_sync_worker
- 或集成到主应用定时任务
"""

import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from agno.utils.log import logger


class OssSyncWorker:
    """
    后台 Worker：扫描未归档文件，异步上传 OSS
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("DATA_DB_PATH")
        if not self.db_path:
            raise RuntimeError("DATA_DB_PATH 未设置")

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def get_pending_files(self, limit: int = 100) -> List[Tuple[str, str, str, str, str]]:
        """获取待同步文件（status='local' 且 oss_url 为空）"""
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
        """更新文件状态"""
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

    def sync_file(self, file_id: str, user_id: str, module: str, filename: str, local_path: str) -> Optional[str]:
        """
        同步单个文件到 OSS。

        Returns:
            OSS URL 或 None（失败时）
        """
        from storage.file_manager import is_oss_enabled

        if not is_oss_enabled():
            return None

        if not os.path.exists(local_path):
            logger.warning(f"本地文件不存在，跳过: {local_path}")
            self.update_status(file_id, "sync_failed")
            return None

        # 获取对应 FileManager
        if module == "data":
            from storage.file_manager import DataFileManager
            fm = DataFileManager()
        elif module == "office":
            from storage.file_manager import OfficeFileManager
            fm = OfficeFileManager()
        elif module == "knowledge":
            from storage.file_manager import KnowledgeFileManager
            fm = KnowledgeFileManager()
        else:
            logger.warning(f"未知模块: {module}，跳过")
            return None

        try:
            oss_url = fm.sync_to_oss(user_id, filename)
            self.update_status(file_id, "synced", oss_url)
            logger.info(f"OSS 同步成功: module={module} filename={filename}")
            return oss_url
        except Exception as e:
            self.update_status(file_id, "sync_failed")
            logger.error(f"OSS 同步失败: module={module} filename={filename} error={e}")
            return None

    def run_once(self, limit: int = 100) -> int:
        """
        执行一轮同步。

        Returns:
            成功同步的文件数
        """
        pending = self.get_pending_files(limit)
        if not pending:
            return 0

        logger.info(f"OSS Worker: 发现 {len(pending)} 个待同步文件")
        synced = 0
        for file_id, user_id, module, filename, local_path in pending:
            self.update_status(file_id, "syncing")
            result = self.sync_file(file_id, user_id, module, filename, local_path)
            if result:
                synced += 1
        return synced

    def run_forever(self, interval_seconds: int = 60) -> None:
        """持续运行，定时扫描"""
        logger.info(f"OSS Worker 启动，间隔 {interval_seconds}s")
        while True:
            try:
                synced = self.run_once()
                if synced:
                    logger.info(f"OSS Worker: 本轮同步 {synced} 个文件")
            except Exception as e:
                logger.error(f"OSS Worker 异常: {e}")
            time.sleep(interval_seconds)


if __name__ == "__main__":
    worker = OssSyncWorker()
    worker.run_forever()
