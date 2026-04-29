"""SQLite 任务追踪数据库管理（原生 sqlite3，无 ORM）。"""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logging import setup_logger
from schemas.job import (
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JobRecord,
)

logger = setup_logger(__name__)

JOB_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    input_video_path TEXT NOT NULL,
    output_dir TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'standard',
    progress REAL NOT NULL DEFAULT 0.0,
    current_step TEXT NOT NULL DEFAULT '',
    edited_video_path TEXT DEFAULT NULL,
    transcript_path TEXT DEFAULT NULL,
    edit_decisions_path TEXT DEFAULT NULL,
    subtitles_path TEXT DEFAULT NULL,
    report_path TEXT DEFAULT NULL,
    error_message TEXT DEFAULT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT DEFAULT NULL,
    completed_at TEXT DEFAULT NULL
);
"""


def _utc_now() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: Path) -> None:
    """初始化 SQLite 数据库，创建 jobs 表。

    参数:
        db_path: 数据库文件路径。父目录将被自动创建。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(JOB_TABLE_SQL)
    conn.commit()
    conn.close()
    logger.info("Database initialized: %s", db_path)


def _connect(db_path: Path) -> sqlite3.Connection:
    """打开 SQLite 数据库连接。"""
    return sqlite3.connect(str(db_path))


def _row_to_job_record(row: tuple) -> JobRecord:
    """将数据库行转换为 JobRecord。"""
    return JobRecord(
        id=row[0],
        status=row[1],
        input_video_path=row[2],
        output_dir=row[3],
        mode=row[4],
        progress=row[5],
        current_step=row[6],
        edited_video_path=row[7],
        transcript_path=row[8],
        edit_decisions_path=row[9],
        subtitles_path=row[10],
        report_path=row[11],
        error_message=row[12],
        created_at=row[13],
        updated_at=row[14],
        started_at=row[15],
        completed_at=row[16],
    )


def create_job(db_path: Path, input_video_path: str, output_dir: str, mode: str = "standard") -> str:
    """在数据库中创建新任务并返回其 UUID。

    参数:
        db_path: 数据库文件路径。
        input_video_path: 输入视频路径。
        output_dir: 输出产物目录。
        mode: 处理模式。

    返回:
        新任务的 UUID 字符串。
    """
    job_id = str(uuid.uuid4())
    now = _utc_now()
    conn = _connect(db_path)
    conn.execute(
        """INSERT INTO jobs (id, status, input_video_path, output_dir, mode,
           progress, current_step, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 0.0, '', ?, ?)""",
        (job_id, JOB_STATUS_PENDING, input_video_path, output_dir, mode, now, now),
    )
    conn.commit()
    conn.close()
    logger.info("Job created: id=%s video=%s", job_id, input_video_path)
    return job_id


def get_job(db_path: Path, job_id: str) -> JobRecord | None:
    """按 ID 查询任务记录。

    参数:
        db_path: 数据库文件路径。
        job_id: 任务 UUID。

    返回:
        找到则返回 JobRecord，否则返回 None。
    """
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT id, status, input_video_path, output_dir, mode, progress, "
        "current_step, edited_video_path, transcript_path, edit_decisions_path, "
        "subtitles_path, report_path, error_message, created_at, updated_at, "
        "started_at, completed_at FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_job_record(row)


def get_next_pending_job(db_path: Path) -> JobRecord | None:
    """获取最早的待处理任务供 Worker 执行。

    参数:
        db_path: 数据库文件路径。

    返回:
        存在待处理任务则返回 JobRecord，否则返回 None。
    """
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT id, status, input_video_path, output_dir, mode, progress, "
        "current_step, edited_video_path, transcript_path, edit_decisions_path, "
        "subtitles_path, report_path, error_message, created_at, updated_at, "
        "started_at, completed_at FROM jobs WHERE status = ? ORDER BY created_at ASC LIMIT 1",
        (JOB_STATUS_PENDING,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_job_record(row)


def mark_job_running(db_path: Path, job_id: str) -> None:
    """将任务标记为运行中，设置 started_at 时间戳。

    参数:
        db_path: 数据库文件路径。
        job_id: 任务 UUID。
    """
    now = _utc_now()
    conn = _connect(db_path)
    conn.execute(
        "UPDATE jobs SET status = ?, started_at = ?, updated_at = ? WHERE id = ?",
        (JOB_STATUS_RUNNING, now, now, job_id),
    )
    conn.commit()
    conn.close()
    logger.info("Job running: id=%s", job_id)


def update_job_status(db_path: Path, job_id: str, progress: float, current_step: str) -> None:
    """更新运行中任务的进度和当前步骤。

    参数:
        db_path: 数据库文件路径。
        job_id: 任务 UUID。
        progress: 进度比例（0.0-1.0）。
        current_step: 当前流水线步骤名称。
    """
    now = _utc_now()
    conn = _connect(db_path)
    conn.execute(
        "UPDATE jobs SET progress = ?, current_step = ?, updated_at = ? WHERE id = ?",
        (progress, current_step, now, job_id),
    )
    conn.commit()
    conn.close()


def update_job_outputs(db_path: Path, job_id: str, **paths: str | None) -> None:
    """更新任务的输出文件路径。

    参数:
        db_path: 数据库文件路径。
        job_id: 任务 UUID。
        **paths: 关键字参数对应输出列（edited_video_path, transcript_path 等）
    """
    now = _utc_now()
    valid_keys = {
        "edited_video_path",
        "transcript_path",
        "edit_decisions_path",
        "subtitles_path",
        "report_path",
    }
    updates = {k: v for k, v in paths.items() if k in valid_keys and v is not None}
    if not updates:
        return

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [now, job_id]

    conn = _connect(db_path)
    conn.execute(f"UPDATE jobs SET {set_clause}, updated_at = ? WHERE id = ?", values)
    conn.commit()
    conn.close()


def mark_job_completed(db_path: Path, job_id: str, **output_paths: str) -> None:
    """将任务标记为已完成，设置 completed_at 和输出路径。

    参数:
        db_path: 数据库文件路径。
        job_id: 任务 UUID。
        **output_paths: 输出文件路径。
    """
    now = _utc_now()
    conn = _connect(db_path)
    conn.execute(
        "UPDATE jobs SET status = ?, progress = 1.0, completed_at = ?, updated_at = ? WHERE id = ?",
        (JOB_STATUS_COMPLETED, now, now, job_id),
    )
    conn.commit()
    conn.close()
    if output_paths:
        update_job_outputs(db_path, job_id, **output_paths)
    logger.info("Job completed: id=%s", job_id)


def mark_job_failed(db_path: Path, job_id: str, error_message: str) -> None:
    """将任务标记为失败并记录错误信息。

    参数:
        db_path: 数据库文件路径。
        job_id: 任务 UUID。
        error_message: 失败描述。
    """
    now = _utc_now()
    conn = _connect(db_path)
    conn.execute(
        "UPDATE jobs SET status = ?, error_message = ?, updated_at = ? WHERE id = ?",
        (JOB_STATUS_FAILED, error_message, now, job_id),
    )
    conn.commit()
    conn.close()
    logger.info("Job failed: id=%s error=%s", job_id, error_message)