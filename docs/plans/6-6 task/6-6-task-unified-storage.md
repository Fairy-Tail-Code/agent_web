# 统一存储模块方案

> 日期：2026-06-06
> 状态：待实施

## 1. 背景与目标

### 1.1 背景

**适用范围**：Data 服务（`Agents/server/data/`）和 Office 服务（`Agents/server/docx_use_mcp/`）的文件存储统一使用本模块。

当前 Data 和 Office 的存储方案存在各自为政的问题：

| 问题 | Data | Office | Knowledge |
|------|------|--------|-----------|
| 用户文件互串 | SQLite 隔离了 data_path，但路径本身无 user_id 前缀 | **无隔离**，所有用户共享目录 | 无追踪 |
| 文件归属追踪 | SQLite `user_data` 表 | **无** | 无 |
| OSS 上传 | `preprocess.py` 可选上传 | `OfficeFileToolkit.upload_to_storage()` 存在但 docx server 不用 | 无 |
| 生命周期管理 | 无 | 无 | 无 |
| 存储逻辑分散 | preprocess.py 各写各的 | docx server 直接写文件 | processor.py 各写各的 |

### 1.2 优化目标

**适用范围**：Data 服务和 Office 服务统一使用本模块。

1. **统一存储抽象层** - Data 和 Office 共用同一套存储逻辑
2. **用户隔离彻底** - 本地路径按 user_id 子目录隔离，两服务互通
3. **SQLite 元数据统一** - 统一表结构记录文件归属，两服务共用同一张表
4. **OSS 归档可选** - 异步上传，不阻塞主流程
5. **模块独立演进** - 各业务模块专注业务，存储托管给 BaseFileManager

### 1.3 适用范围

| 服务 | 使用哪个 FileManager | 说明 |
|------|---------------------|------|
| `Agents/server/data/` | `DataFileManager` | CSV 数据文件、ML 模型 |
| `Agents/server/docx_use_mcp/` | `OfficeFileManager` | DOCX/PDF/MD 等办公文档 |
| 未来扩展 | 继承 `BaseFileManager` | 新服务也用统一存储 |

---

## 2. 目标架构

### 2.1 模块层次

**适用范围**：Data 服务（`Agents/server/data/`）和 Office 服务（`Agents/server/docx_use_mcp/`）统一使用 `BaseFileManager`。

```
┌─────────────────────────────────────────────────────────────┐
│                      业务层                                  │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │   Agents/server/data/           │  │  Agents/server/docx_use_mcp/  │  │
│  │   DataFileManager         │  │  OfficeFileManager      │  │
│  └─────────────┬───────────┘  └──────────────┬──────────┘  │
└───────────────┼──────────────────────────────┼──────────────┘
                │                              │
                ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   storage/file_manager.py                    │
│                    统一存储抽象层                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 BaseFileManager                      │   │
│  │  - 用户隔离路径解析                                  │   │
│  │  - SQLite 元数据读写（两服务共用同一表）              │   │
│  │  - OSS 异步归档                                    │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────┐
│                    存储介质层                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │ 本地文件系统  │  │  SQLite     │  │  OSS(七牛云)  │        │
│  │ user_cache/ │  │ storage.files│  │  异步归档    │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

**上传流程（Data 为例）**：
```
用户上传
    │
    ▼
DataFileManager.save_local(user_id, content, filename)
    │
    ├─► 本地路径: user_cache/data/{user_id}/{filename}
    │
    ├─► SQLite: storage.files INSERT
    │
    └─► OssSyncWorker 异步上传 → oss://bucket/data/{user_id}/{filename}
```

**处理流程（Data 为例）**：
```
DataFileManager.get_path(user_id)
    │
    ├─► 查 SQLite storage.files
    │
    ├─► 返回本地路径
    │
    └─► 处理函数直接读写本地路径
```

**Office 输出流程**：
```
Agent 调用 docx_use_mcp
    │
    ▼
OfficeFileManager.get_output_dir(user_id, "docx")
    │
    ├─► 返回: user_cache/office/{user_id}/output/docx/
    │
    ├─► docx server 写文件到这个目录
    │
    └─► OfficeFileManager.register(user_id, file_path, format="docx")
```

---

## 3. 详细设计

### 3.1 SQLite Schema

```sql
-- 统一文件元数据表
CREATE TABLE IF NOT EXISTS storage.files (
    file_id      TEXT PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      TEXT NOT NULL,
    module       TEXT NOT NULL,          -- data / office / knowledge
    filename     TEXT NOT NULL,
    local_path   TEXT NOT NULL,
    oss_url      TEXT,
    file_size    BIGINT,
    mime_type    TEXT,
    status       TEXT DEFAULT 'local',   -- local / syncing / synced
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT uk_user_module_filename UNIQUE (user_id, module, filename)
);

CREATE INDEX IF NOT EXISTS idx_storage_user_id ON storage.files(user_id);
CREATE INDEX IF NOT EXISTS idx_storage_module ON storage.files(module);
CREATE INDEX IF NOT EXISTS idx_storage_status ON storage.files(status);
```

### 3.2 `storage/file_manager.py`

```python
"""
统一存储抽象层
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union
import uuid

import os
import sqlite3

from dotenv import load_dotenv
from agno.utils.log import logger

load_dotenv()


# === OSS 配置检查 ===

def is_oss_enabled() -> bool:
    """检查 OSS 是否真正可用"""
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


# === 基类 ===

class BaseFileManager(ABC):
    """
    所有文件管理器的基类

    提供：
    - 用户目录隔离
    - SQLite 元数据管理
    - OSS 异步归档
    - 统一异常处理
    """

    # 子类必须定义
    module: str = ""

    def __init__(self):
        self.storage = self._get_storage()
        self._ensure_base_dir()

    def _get_storage(self):
        """获取 OSS 存储实例"""
        try:
            from storage import get_qiniu_storage
            return get_qiniu_storage()
        except Exception:
            return None

    @abstractmethod
    def get_base_dir(self, user_id: str) -> Path:
        """子类返回本地根目录"""

    @abstractmethod
    def get_module_prefix(self) -> str:
        """子类返回 OSS 路径前缀"""

    def _ensure_base_dir(self):
        """确保根目录存在"""
        base = self.get_base_dir("*")  # 通配符，获取模块根目录
        base.mkdir(parents=True, exist_ok=True)

    # === 通用能力 ===

    def _safe_user_segment(self, user_id: str) -> str:
        """将 user_id 转为安全的目录名"""
        raw = str(user_id).strip()
        if not raw:
            return "anonymous"
        return "".join(
            ch if ch.isalnum() or ch in {"-", "_", "."} else "_"
            for ch in raw
        ).strip("._") or "anonymous"

    def _get_user_dir(self, user_id: str) -> Path:
        """获取用户目录"""
        base = self.get_base_dir("*")
        user_dir = base / self._safe_user_segment(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _get_db_path(self) -> str:
        """获取元数据库路径"""
        db_path = os.getenv("DATA_DB_PATH")
        if not db_path:
            raise RuntimeError("DATA_DB_PATH 未设置")
        return db_path

    def _get_connection(self):
        return sqlite3.connect(self._get_db_path())

    # === 本地文件操作 ===

    def save_local(
        self,
        user_id: str,
        content: Union[bytes, Path],
        filename: str,
    ) -> str:
        """
        保存文件到本地

        Args:
            user_id: 用户 ID
            content: 文件内容(bytes)或本地路径(Path)
            filename: 文件名

        Returns:
            本地绝对路径
        """
        user_dir = self._get_user_dir(user_id)
        safe_filename = self._sanitize_filename(filename)
        dest_path = user_dir / safe_filename

        if isinstance(content, bytes):
            tmp_path = dest_path.with_suffix(".tmp")
            with open(tmp_path, "wb") as f:
                f.write(content)
            tmp_path.replace(dest_path)
        else:
            # content 是本地路径，复制
            import shutil
            shutil.copy2(str(content), str(dest_path))

        logger.info(f"文件已保存: user_id={user_id} path={dest_path}")
        return str(dest_path)

    def _sanitize_filename(self, filename: str) -> str:
        """sanitize 文件名"""
        import re
        name = Path(filename).name or "unnamed"
        return re.sub(r"[^\w\-_. ]", "_", name)

    def get_path(self, user_id: str, filename: Optional[str] = None) -> str:
        """
        获取本地路径（从 SQLite 查询最新记录）

        Args:
            user_id: 用户 ID
            filename: 可选，指定文件名

        Returns:
            本地绝对路径
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if filename:
                cursor.execute(
                    "SELECT local_path FROM storage.files "
                    "WHERE user_id = ? AND module = ? AND filename = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (user_id, self.module, filename),
                )
            else:
                cursor.execute(
                    "SELECT local_path FROM storage.files "
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
                    path = self._download_from_oss(oss_url, user_id)
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
        注册文件到 SQLite 元数据表

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
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO storage.files
                (user_id, module, filename, local_path, file_size, mime_type, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'local', ?, ?)
                ON CONFLICT (user_id, module, filename) DO UPDATE SET
                    local_path = EXCLUDED.local_path,
                    file_size = EXCLUDED.file_size,
                    mime_type = EXCLUDED.mime_type,
                    status = 'local',
                    updated_at = EXCLUDED.updated_at
            """, (user_id, self.module, filename, local_path, file_size, mime_type, now, now))
            conn.commit()
            logger.info(f"文件已注册: user_id={user_id} module={self.module} filename={filename}")
        finally:
            conn.close()

        return FileMetadata(
            file_id=str(uuid.uuid4()),
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
                    "SELECT oss_url FROM storage.files "
                    "WHERE user_id = ? AND module = ? AND filename = ? AND status = 'synced'",
                    (user_id, self.module, filename),
                )
            else:
                cursor.execute(
                    "SELECT oss_url FROM storage.files "
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
        safe_user = self._safe_user_segment(user_id)
        safe_filename = self._sanitize_filename(filename)
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
        oss_key = self._build_oss_key(user_id, filename)

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
                    UPDATE storage.files
                    SET status = ?, oss_url = ?, updated_at = ?
                    WHERE user_id = ? AND module = ? AND filename = ?
                """, (status, oss_url, now, user_id, self.module, filename))
            else:
                cursor.execute("""
                    UPDATE storage.files
                    SET status = ?, updated_at = ?
                    WHERE user_id = ? AND module = ? AND filename = ?
                """, (status, now, user_id, self.module, filename))
            conn.commit()
        finally:
            conn.close()

    def _download_from_oss(self, oss_url: str, user_id: str) -> str:
        """从 OSS 下载文件到本地"""
        # 实现：从 OSS URL 下载，恢复到本地路径
        # ...


# === 子类实现 ===

class DataFileManager(BaseFileManager):
    """Data 模块文件管理器"""

    module = "data"

    def get_base_dir(self, user_id: str) -> Path:
        base = Path(os.getenv("DATA_UPLOAD_DIR", "./user_cache/data"))
        if user_id == "*":
            return base
        return base / self._safe_user_segment(user_id)

    def get_module_prefix(self) -> str:
        return "data"

    def get_csv_path(self, user_id: str) -> str:
        """Data 专用：获取 CSV 路径"""
        return self.get_path(user_id, filename=None)

    def load_csv(self, user_id: str) -> "pd.DataFrame":
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
        return base / self._safe_user_segment(user_id)

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
        safe_filename = self._sanitize_filename(filename)
        # 确保扩展名匹配格式
        ext = self._get_extension_for_format(format)
        if not safe_filename.lower().endswith(ext):
            safe_filename = f"{safe_filename}{ext}"
        return str((output_dir / safe_filename).resolve())

    def _get_extension_for_format(self, format: str) -> str:
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
        return base / self._safe_user_segment(user_id)

    def get_module_prefix(self) -> str:
        return "knowledge"
```

### 3.3 SQLite 建表迁移

```sql
-- 新增 storage schema 和 files 表
CREATE SCHEMA IF NOT EXISTS storage;

CREATE TABLE IF NOT EXISTS storage.files (
    file_id      TEXT PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      TEXT NOT NULL,
    module       TEXT NOT NULL,
    filename     TEXT NOT NULL,
    local_path   TEXT NOT NULL,
    oss_url      TEXT,
    file_size    BIGINT,
    mime_type    TEXT,
    status       TEXT DEFAULT 'local',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT uk_user_module_filename UNIQUE (user_id, module, filename)
);

CREATE INDEX IF NOT EXISTS idx_storage_user_id ON storage.files(user_id);
CREATE INDEX IF NOT EXISTS idx_storage_module ON storage.files(module);
CREATE INDEX IF NOT EXISTS idx_storage_status ON storage.files(status);
```

---

## 4. 改造清单

**适用范围**：Data 服务和 Office 服务统一使用 `storage/file_manager.py`。

### 4.1 新增文件

| 文件 | 职责 |
|------|------|
| `storage/file_manager.py` | 统一存储抽象层（Data 和 Office 共用） |

### 4.2 Data 服务改造（`Agents/server/data/`）

| 文件 | 改动 |
|------|------|
| `hook/preprocess.py` | `DataFileManager` 替代原有上传逻辑 |
| `Agents/server/data/data_process/data_preprocessing.py` | `DataFileManager.get_csv_path()` 替代 `_get_data_path_by_user()` |
| `Agents/server/data/machine_learning/machine_learning_model.py` | `DataFileManager` 替代路径解析 |

### 4.3 Office 服务改造（`Agents/server/docx_use_mcp/`）

| 文件 | 改动 |
|------|------|
| `tools/office_file_toolkit.py` | `OfficeFileManager` 替代原有工具 |
| `Agents/server/docx_use_mcp/docx_use_server/tools/document_tools.py` | 接受 user_id 参数，写入 user_id 隔离目录 |

### 4.4 公共改造

| 文件 | 改动 |
|------|------|
| `auth/user_db.py` | 添加 `storage.files` 建表 SQL |

### 4.5 线程池/进程池生命周期管理

**现状问题**：
- `task_pool.py` 和 `process_pool.py` 的 `shutdown()` 函数定义了但从未调用
- 进程退出时依赖 Python GC 被动回收
- 无启动初始化，无健康检查
- fork 后子进程线程池状态不确定

**改进方案**：Lifespan 模式（方案B）

#### 4.5.1 `Agents/server/data/data_process/task_pool.py` 改造

```python
# 新增 lifespan 支持
import atexit
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

_executor: Optional[ThreadPoolExecutor] = None

def get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        import os
        _executor = ThreadPoolExecutor(max_workers=os.cpu_count() or 4)
    return _executor

def shutdown() -> None:
    """显式关闭线程池"""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None

# 注册 atexit 兜底清理
atexit.register(shutdown)

# fork 后重新初始化（进程池需要）
os.register_at_fork(after_in_child=lambda: globals().update({'_executor': None}))
```

#### 4.5.2 `Agents/server/data/machine_learning/process_pool.py` 改造

```python
# 同上结构
import atexit
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Optional

_TRAIN_EXECUTOR: Optional[ProcessPoolExecutor] = None

def get_train_executor() -> ProcessPoolExecutor:
    global _TRAIN_EXECUTOR
    if _TRAIN_EXECUTOR is None:
        _TRAIN_EXECUTOR = ProcessPoolExecutor(max_workers=max(os.cpu_count() or 2, 2))
    return _TRAIN_EXECUTOR

def shutdown_train_executor() -> None:
    """显式关闭训练进程池"""
    global _TRAIN_EXECUTOR
    if _TRAIN_EXECUTOR is not None:
        _TRAIN_EXECUTOR.shutdown(wait=True)
        _TRAIN_EXECUTOR = None

atexit.register(shutdown_train_executor)

# fork 后重新初始化
os.register_at_fork(after_in_child=lambda: globals().update({'_TRAIN_EXECUTOR': None}))
```

#### 4.5.3 在 FastMCP 启动时初始化（可选）

如果后续 MCP 服务需要更精细的生命周期控制，可以在 `Agents/server/data/main.py` 中：

```python
# Agents/server/data/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI

_pool_executor = None
_train_executor = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化
    global _pool_executor, _train_executor
    from server.data.data_process.task_pool import get_executor
    from Agents.server.data.machine_learning.process_pool import get_train_executor
    get_executor()
    get_train_executor()
    yield
    # 关闭时清理
    from server.data.data_process.task_pool import shutdown
    from Agents.server.data.machine_learning.process_pool import shutdown_train_executor
    shutdown()
    shutdown_train_executor()

data_mcp_app = FastAPI(lifespan=lifespan)
```

**后续扩展**：如果未来 MCP 服务过多、资源不够，可以考虑 MCP 懒加载（当前不在本 plan 范围）。

### 4.6 改造示例

**`hook/preprocess.py` 改造前 vs 改造后**：

```python
# 改造前
def preprocess_hook(run_input: RunInput) -> dict:
    dest_path = target_dir / file_name
    with open(dest_path, "wb") as f:
        f.write(file.content)
    _save_to_db(user_id, str(dest_path))  # 写自己维护的 user_data 表

# 改造后
def preprocess_hook(run_input: RunInput) -> dict:
    fm = DataFileManager()
    local_path = fm.save_local(user_id, file.content, filename)
    fm.register(user_id, local_path, filename=filename, file_size=len(file.content))
    # OSS 异步归档由 OssSyncWorker 处理
```

**`Agents/server/docx_use_mcp/docx_use_server/tools/document_tools.py` 改造**：

```python
# 改造前
async def create_document(filename: str, title: str = None, author: str = None):
    filename = ensure_docx_extension(filename)
    doc.save(filename)  # 直接写，无用户隔离

# 改造后
async def create_document(
    filename: str,
    title: str = None,
    author: str = None,
    user_id: str = "default"  # 新增参数
):
    from storage.file_manager import OfficeFileManager
    fm = OfficeFileManager()
    file_path = fm.build_output_path(user_id, filename, "docx")
    doc.save(file_path)
    fm.register(user_id, file_path, filename=filename)
    return file_path
```

---

## 5. OSS 异步归档 Worker

```python
# storage/oss_sync_worker.py

import asyncio
from datetime import datetime, timezone
import os

class OssSyncWorker:
    """
    后台 Worker：扫描未归档文件，异步上传 OSS

    使用方式：
    - 作为独立进程启动: python -m storage.oss_sync_worker
    - 或集成到主应用定时任务
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.getenv("DATA_DB_PATH")

    def get_pending_files(self, limit: int = 100):
        """获取待同步文件"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT file_id, user_id, module, filename, local_path
                FROM storage.files
                WHERE status = 'local' AND oss_url IS NULL
                ORDER BY created_at ASC
                LIMIT ?
            """, (limit,))
            return cursor.fetchall()
        finally:
            conn.close()

    def update_status(self, file_id: str, status: str, oss_url: str = None):
        """更新状态"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            if oss_url:
                cursor.execute("""
                    UPDATE storage.files
                    SET status = ?, oss_url = ?, updated_at = ?
                    WHERE file_id = ?
                """, (status, oss_url, now, file_id))
            else:
                cursor.execute("""
                    UPDATE storage.files
                    SET status = ?, updated_at = ?
                    WHERE file_id = ?
                """, (status, now, file_id))
            conn.commit()
        finally:
            conn.close()

    async def sync_file(self, file_id: str, user_id: str, module: str, filename: str, local_path: str):
        """同步单个文件到 OSS"""
        from storage.file_manager import is_oss_enabled, BaseFileManager

        if not is_oss_enabled():
            return

        # 获取对应 FileManager
        if module == "data":
            fm = DataFileManager()
        elif module == "office":
            fm = OfficeFileManager()
        elif module == "knowledge":
            fm = KnowledgeFileManager()
        else:
            return

        try:
            oss_url = fm.sync_to_oss(user_id, filename)
            self.update_status(file_id, "synced", oss_url)
        except Exception as e:
            self.update_status(file_id, "sync_failed")
            raise e

    async def run_once(self, limit: int = 100):
        """执行一轮同步"""
        pending = self.get_pending_files(limit)
        for file_id, user_id, module, filename, local_path in pending:
            self.update_status(file_id, "syncing")
            try:
                await self.sync_file(file_id, user_id, module, filename, local_path)
            except Exception:
                pass  # 失败则下次重试

    def run_forever(self, interval_seconds: int = 60):
        """持续运行"""
        while True:
            asyncio.run(self.run_once())
            import time
            time.sleep(interval_seconds)


if __name__ == "__main__":
    worker = OssSyncWorker()
    worker.run_forever()
```

---

## 6. 实施计划

### 6.1 优先级

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| **Phase 1** | `storage/file_manager.py` 核心实现 | P0 |
| **Phase 1** | `auth/user_db.py` 添加建表 SQL | P0 |
| **Phase 1** | 线程池/进程池生命周期管理（atexit + fork 重新初始化） | P0 |
| **Phase 2** | `hook/preprocess.py` 改用 DataFileManager | P1 |
| **Phase 2** | `Agents/server/data/` 改用 DataFileManager | P1 |
| **Phase 3** | `tools/office_file_toolkit.py` 改用 OfficeFileManager | P2 |
| **Phase 3** | `Agents/server/docx_use_mcp/` 改用 OfficeFileManager | P2 |
| **Phase 4** | `knowledge/` 改用 KnowledgeFileManager | P2 |
| **Phase 4** | `storage/oss_sync_worker.py` 后台归档 Worker | P2 |

### 6.2 注意事项

1. **向后兼容**：改造过程中保持原有接口不变，通过参数控制走新/旧逻辑
2. **数据迁移**：`storage.files` 表是新增，不影响现有 `user_data` 表
3. **测试**：先写单元测试，再逐步替换
4. **开关**：可通过 `USE_UNIFIED_STORAGE=true/false` 切换新旧逻辑

---

## 7. 目录结构（改造后）

```
agent_web/
├── Agents/
│   ├── agent/                 # Agent 定义
│   ├── team/                 # Team 定义
│   ├── tools/               # Toolkit 定义
│   │   ├── office_file_toolkit.py  # 改造：使用 OfficeFileManager
│   │   └── office_docx_toolkit.py # 新增（docx 合并后）
│   ├── knowledge/           # 知识库
│   │   └── processor.py     # 改造：使用 KnowledgeFileManager
│   └── server/
│       ├── data/            # Data MCP 服务
│       │   ├── data_process/
│       │   │   └── data_preprocessing.py   # 改造：使用 DataFileManager
│       │   ├── machine_learning/
│       │   │   └── machine_learning_model.py  # 改造：使用 DataFileManager
│       │   ├── data_process/task_pool.py  # 改造：线程池生命周期
│       │   └── machine_learning/process_pool.py  # 改造：进程池生命周期
│       └── docx_use_mcp/   # 待合并，不再作为独立 MCP
│           └── docx_use_server/
│
├── api/                      # FastAPI 入口
├── auth/
│   └── user_db.py          # 改造：添加 storage.files 建表
├── storage/                 # OSS 存储能力
│   ├── qiniu_storage.py    # 现有 OSS 封装
│   ├── file_manager.py      # 新增：统一存储抽象层
│   └── oss_sync_worker.py  # 新增：后台归档 Worker
├── hook/
│   └── preprocess.py       # 改造：使用 DataFileManager
└── config/                   # 配置
```

---

## 8. 与其他任务的关系

- **本 plan** 是 `6-6-task-login-security.md` 的并行任务，同属 Phase 1 基础设施优化
- **本 plan** 与 `docx 合并进 toolkit` 任务（见 PROMPT.md 任务二）共享 `storage/file_manager.py`
- **代码清理**（`6-6-task-code-cleanup.md`）可与本任务并行
- **本 plan** 是 `6-6-task-login-security.md` 的并行 plan，同属 Phase 1 基础设施优化

---

*文档创建日期：2026-06-06*
*方案状态：待实施*
