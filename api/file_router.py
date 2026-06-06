"""文件管理路由 —— 列出和下载 Agent 生成的文件。

Agent 生成文件保存在 /app/user_cache/ 下，此路由提供：
  - GET  /files/list             按用户列出文件（支持子目录过滤）
  - GET  /files/download/{path}  下载指定文件（JWT 鉴权 + 路径安全检查）
"""
from __future__ import annotations

import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from auth.model import CurrentUser
from auth.permissions import get_current_user

file_router = APIRouter(prefix="/files", tags=["files"])

# ── 常量 ──────────────────────────────────────────────────────
# 文件根目录，与 docker-compose 中的 agent_user_cache volume 对应
BASE_DIR = Path(os.getenv("FILE_SERVE_ROOT", "/app/user_cache")).resolve()

# 允许下载的子目录白名单（相对于 BASE_DIR）
ALLOWED_SUBDIRS = {"office/output", "workspace"}

# 允许下载的文件扩展名（小写）
ALLOWED_EXTENSIONS = {
    ".docx", ".doc", ".pdf", ".xlsx", ".xls", ".csv", ".tsv",
    ".md", ".txt", ".json", ".png", ".jpg", ".jpeg", ".gif",
    ".pptx", ".ppt", ".zip", ".html",
}

# 单个文件最大允许下载大小（100 MB）
MAX_FILE_SIZE = 100 * 1024 * 1024


# ── Pydantic Models ───────────────────────────────────────────
class FileInfo(BaseModel):
    name: str
    path: str                       # 相对路径，用于 download 接口
    size: int                       # 字节数
    modified: str                   # ISO8601 时间戳
    is_dir: bool = False
    extension: str = ""             # 文件扩展名（小写，含点）


class FileListResponse(BaseModel):
    files: list[FileInfo]
    total: int


# ── 工具函数 ───────────────────────────────────────────────────
def _safe_resolve(relative_path: str) -> Path:
    """解析相对路径并确保不逃逸 BASE_DIR。"""
    resolved = (BASE_DIR / relative_path).resolve()
    if not str(resolved).startswith(str(BASE_DIR)):
        raise HTTPException(status_code=403, detail="路径不允许")
    return resolved


def _is_allowed_file(path: Path) -> bool:
    """检查文件是否在白名单内。"""
    if path.is_dir():
        return True
    return path.suffix.lower() in ALLOWED_EXTENSIONS


def _path_in_allowed_subdir(path: Path) -> bool:
    """检查路径是否在允许的子目录下。"""
    try:
        rel = path.relative_to(BASE_DIR)
    except ValueError:
        return False
    parts = rel.parts
    if not parts:
        return False
    # 拼接前两级作为子目录前缀
    prefix = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
    return prefix in ALLOWED_SUBDIRS or any(
        prefix.startswith(d) for d in ALLOWED_SUBDIRS
    )


def _file_to_info(path: Path, rel_path: str) -> FileInfo:
    """将 Path 转为 FileInfo。"""
    try:
        st = path.stat()
    except OSError:
        st = None
    return FileInfo(
        name=path.name,
        path=rel_path,
        size=st.st_size if st and not stat.S_ISDIR(st.st_mode) else 0,
        modified=datetime.fromtimestamp(st.st_mtime).isoformat() if st else "",
        is_dir=path.is_dir(),
        extension=path.suffix.lower(),
    )


# ── 路由 ──────────────────────────────────────────────────────
@file_router.get("/list", response_model=FileListResponse)
async def list_files(
    subdir: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    """列出用户可下载的文件。

    Args:
        subdir: 可选，过滤子目录（如 "office/output/docx"）。
                不传则列出所有允许的子目录下的文件。
    """
    if subdir:
        scan_dir = _safe_resolve(subdir)
        if not _path_in_allowed_subdir(scan_dir):
            raise HTTPException(status_code=403, detail="目录不在允许范围")
        if not scan_dir.is_dir():
            raise HTTPException(status_code=404, detail="目录不存在")
        items = list(scan_dir.iterdir())
    else:
        # 列出所有允许子目录下的文件（平铺）
        items = []
        for allowed in ALLOWED_SUBDIRS:
            d = BASE_DIR / allowed
            if d.is_dir():
                items.extend(d.rglob("*"))

    files: list[FileInfo] = []
    for item in items:
        if not _is_allowed_file(item):
            continue
        try:
            rel = str(item.relative_to(BASE_DIR))
        except ValueError:
            continue
        files.append(_file_to_info(item, rel))

    # 按修改时间倒序
    files.sort(key=lambda f: f.modified, reverse=True)
    return FileListResponse(files=files, total=len(files))


@file_router.get("/download/{file_path:path}")
async def download_file(
    file_path: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """下载指定文件。

    file_path 为相对于 FILE_SERVE_ROOT 的路径，
    例如 "office/output/docx/xxx.docx"。
    """
    resolved = _safe_resolve(file_path)

    # 安全检查
    if not _path_in_allowed_subdir(resolved):
        raise HTTPException(status_code=403, detail="目录不在允许范围")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    if not _is_allowed_file(resolved):
        raise HTTPException(status_code=403, detail="不支持的文件类型")

    st = resolved.stat()
    if st.st_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="文件过大")

    return FileResponse(
        path=str(resolved),
        filename=resolved.name,
        media_type="application/octet-stream",
    )
