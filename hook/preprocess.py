import os
import sqlite3
import uuid
from pathlib import Path

from agno.run.agent import RunInput
from agno.utils.log import logger
from storage.file_manager import DataFileManager

WORKSPACE_ROOT = Path(os.getenv("DATA_UPLOAD_DIR", Path(__file__).resolve().parents[1] / "user_cache" / "workspace"))

# 是否启用统一存储（DataFileManager），默认启用
_USE_UNIFIED = os.getenv("USE_UNIFIED_STORAGE", "true").lower() == "true"


def _resolve_user_id(run_input: RunInput) -> str:
    """从 RunInput 解析 user_id"""
    metadata = getattr(run_input, "metadata", None)
    if isinstance(metadata, dict):
        for key in ("user_id", "sub"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    direct_user_id = getattr(run_input, "user_id", None)
    if isinstance(direct_user_id, str) and direct_user_id.strip():
        return direct_user_id.strip()

    fallback_user_id = os.getenv("DEFAULT_DATA_USER_ID", "anonymous")
    logger.warning(f"未从请求上下文解析到 user_id，回退到默认标识: {fallback_user_id}")
    return fallback_user_id


def _save_to_db_legacy(user_id: str, data_path: str) -> None:
    """旧版：将文件映射写入 user_data 表（向后兼容）"""
    db_path = os.getenv("DATA_DB_PATH")
    if not db_path:
        raise RuntimeError("环境变量 DATA_DB_PATH 未设置，无法写入元数据库")

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_data (
                    user_id   TEXT NOT NULL,
                    data_path TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                "INSERT INTO user_data (user_id, data_path) VALUES (?, ?)",
                (user_id, data_path),
            )
            conn.commit()
            logger.info(f"已写入数据映射(legacy): user_id={user_id}, data_path={data_path}")
    except sqlite3.Error as exc:
        raise RuntimeError(f"写入元数据库失败: {exc}") from exc


def preprocess_hook(run_input: RunInput) -> dict:
    """
    文件上传预处理钩子。

    当 USE_UNIFIED_STORAGE=true（默认）时：
        使用 DataFileManager 保存文件到用户隔离目录 + 注册到 storage_files 表，
        OSS 归档由 OssSyncWorker 异步处理。

    当 USE_UNIFIED_STORAGE=false 时：
        保持原有逻辑：保存到 workspace 临时目录 + 同步上传七牛云 + 写入 user_data 表。
    """
    user_id = _resolve_user_id(run_input)

    # 存储所有文件的 本地路径 / 云端URL
    file_paths: list[str] = []
    file_urls: list[str] = []

    if not run_input.files:
        logger.warning("⚠️ 当前请求未接收到任何有效文件")
        return {}

    if _USE_UNIFIED:
        # ── 新逻辑：DataFileManager ──
        fm = DataFileManager()

        for file in run_input.files:
            file_name = (
                getattr(file, "name", None)
                or getattr(file, "filename", None)
                or f"upload_{uuid.uuid4().hex[:8]}"
            )

            try:
                local_path = fm.save_local(user_id, file.content, file_name)
                fm.register(
                    user_id, local_path,
                    filename=file_name,
                    file_size=len(file.content) if file.content else 0,
                )
                # 也写入旧表，保证向后兼容
                _save_to_db_legacy(user_id, local_path)
            except Exception as e:
                logger.error(f"文件保存失败 | user_id={user_id} | file={file_name} | err={str(e)}")
                continue

            file.filepath = local_path
            file_paths.append(local_path)
            # file_urls 留空，OSS 异步归档
    else:
        # ── 旧逻辑：workspace + 同步 OSS ──
        from storage import get_qiniu_storage

        target_dir = WORKSPACE_ROOT / DataFileManager.safe_user_segment(user_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        storage = get_qiniu_storage()

        for file in run_input.files:
            file_name = (
                getattr(file, "name", None)
                or getattr(file, "filename", None)
                or f"upload_{uuid.uuid4().hex[:8]}"
            )

            dest_path = target_dir / file_name
            try:
                with open(dest_path, "wb") as f:
                    f.write(file.content)
                logger.info(f"文件本地保存成功 | user_id={user_id} | path={dest_path}")
            except Exception as e:
                logger.error(f"文件本地保存失败 | user_id={user_id} | file={file_name} | err={str(e)}")
                continue

            try:
                file_url = storage.upload_file(
                    module="data",
                    user_id=user_id,
                    file_path=dest_path,
                    filename=file_name,
                )
                logger.info(f"七牛云上传成功 | user_id={user_id} | url={file_url}")
                file_urls.append(file_url)
                try:
                    dest_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"删除本地临时文件失败: {dest_path}, {e}")
            except Exception as exc:
                logger.error(f"七牛云上传失败 | err={str(exc)}")
                error_msg = f"🚫 {file_name} 文件上传七牛云失败，功能维护中，暂不可使用。\n   错误信息：{str(exc)}"
                run_input.input_content = (
                    f"{error_msg}\n\n{run_input.input_content}"
                    if run_input.input_content else error_msg
                )
                continue

            file.filepath = str(dest_path)
            file_paths.append(str(dest_path))

            if file_urls:
                try:
                    _save_to_db_legacy(user_id, file_urls[-1])
                except RuntimeError as exc:
                    logger.error(f"数据库写入失败，已跳过 | err={str(exc)}")

    # 打印本次处理总文件数
    logger.info(f"文件处理完成 | 总数={len(file_paths)} | user_id={user_id}")

    # 拼接文件处理结果到输入内容
    if file_paths:
        result_lines = [f"✅ 成功接收 {len(file_paths)} 个文件：\n"]

        for path in file_paths:
            if os.path.exists(path):
                file_size = os.path.getsize(path)
                size_mb = round(file_size / (1024 * 1024), 2)
            else:
                size_mb = 0.0

            entry = f"📄 {os.path.basename(path)}\n   文件大小: {size_mb} MB\n"
            # 如果有对应的 OSS URL，也展示
            if file_urls:
                idx = file_paths.index(path)
                if idx < len(file_urls):
                    entry += f"   云存储URL: {file_urls[idx]}\n"
            entry += "----------------------------------------\n"
            result_lines.append(entry)

        result = "".join(result_lines)
        logger.info("\n" + result)

        original_input = run_input.input_content or ""
        run_input.input_content = f"{result}\n{original_input}"
    else:
        logger.warning("⚠️ 当前请求未接收到任何有效文件")

    return {}
