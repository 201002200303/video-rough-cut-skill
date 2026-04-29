"""FastAPI 应用入口。"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from api.db import init_db, create_job, get_job
from api.models import (
    CreateJobRequest,
    CreateJobResponse,
    JobStatusResponse,
    JobOutputsResponse,
    ALLOWED_EXTENSIONS,
)
from core.config import load_env
from core.logging import setup_logger
from core.paths import ensure_output_dir
from schemas.job import JOB_STATUS_PENDING

logger = setup_logger(__name__)


def get_db_path() -> Path:
    """从环境变量或默认值返回数据库路径。"""
    path_str = os.getenv("VIDEO_SKILL_DB_PATH", "./video_skill.db")
    return Path(path_str).resolve()


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_env()
    db_path = get_db_path()
    init_db(db_path)
    logger.info("App started, db=%s", db_path)
    yield


app = FastAPI(
    title="Video Rough Cut Skill",
    version="0.1.0",
    description="中文口述视频自动粗剪 MVP API",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/jobs", response_model=CreateJobResponse)
async def post_job(req: CreateJobRequest):
    """创建新的视频粗剪任务。"""
    db_path = get_db_path()
    video_path = Path(req.input_video_path)
    if not video_path.exists():
        raise HTTPException(status_code=400, detail=f"Input video not found: {req.input_video_path}")

    ext = video_path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension: {ext}. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    output_dir = Path(req.output_dir).resolve()
    ensure_output_dir(str(output_dir))

    job_id = create_job(db_path, str(video_path), str(output_dir), req.mode)
    logger.info("Job created: id=%s video=%s", job_id, video_path)
    return CreateJobResponse(job_id=job_id, status=JOB_STATUS_PENDING, output_dir=str(output_dir))


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """获取任务状态。"""
    db_path = get_db_path()
    job = get_job(db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@app.get("/jobs/{job_id}/outputs", response_model=JobOutputsResponse)
async def get_job_outputs(job_id: str):
    """获取任务输出：完成时返回路径，运行中返回进度，失败时返回错误。"""
    db_path = get_db_path()
    job = get_job(db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return JobOutputsResponse(
        status=job.status,
        current_step=job.current_step,
        progress=job.progress,
        error_message=job.error_message,
        edited_video_path=job.edited_video_path,
        transcript_path=job.transcript_path,
        edit_decisions_path=job.edit_decisions_path,
        subtitles_path=job.subtitles_path,
        report_path=job.report_path,
    )