"""任务追踪 Pydantic 模型。"""

from pydantic import BaseModel, Field, field_validator


# 任务状态常量
JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"

VALID_JOB_STATUSES = (JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_COMPLETED, JOB_STATUS_FAILED)


class JobStatus(BaseModel):
    """任务状态查询/响应模型。"""

    id: str = Field(..., description="Job UUID")
    status: str = Field(..., description="Job status: pending, running, completed, failed")
    progress: float = Field(default=0.0, description="Progress fraction 0.0-1.0")
    current_step: str = Field(default="", description="Current pipeline step name")
    error_message: str | None = Field(default=None, description="Error message if failed")

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        if v not in VALID_JOB_STATUSES:
            raise ValueError(f"status must be one of {VALID_JOB_STATUSES}")
        return v


class JobRecord(BaseModel):
    """与 SQLite jobs 表行匹配的模型。"""

    id: str = Field(..., description="Job UUID (primary key)")
    status: str = Field(default=JOB_STATUS_PENDING, description="Job status")
    input_video_path: str = Field(..., description="Path to the input video")
    output_dir: str = Field(..., description="Directory for output artifacts")
    mode: str = Field(default="standard", description="Processing mode")
    progress: float = Field(default=0.0, description="Progress fraction 0.0-1.0")
    current_step: str = Field(default="", description="Current pipeline step")
    edited_video_path: str | None = Field(default=None)
    transcript_path: str | None = Field(default=None)
    edit_decisions_path: str | None = Field(default=None)
    subtitles_path: str | None = Field(default=None)
    report_path: str | None = Field(default=None)
    error_message: str | None = Field(default=None)
    created_at: str = Field(..., description="UTC ISO timestamp of job creation")
    updated_at: str = Field(..., description="UTC ISO timestamp of last update")
    started_at: str | None = Field(default=None, description="UTC ISO timestamp when job started running")
    completed_at: str | None = Field(default=None, description="UTC ISO timestamp when job completed")