"""API 请求/响应模型与流水线步骤常量。"""

from pydantic import BaseModel, Field, field_validator

# ── 流水线步骤常量 ──

STEP_EXTRACT_AUDIO = "extract_audio"
STEP_TRANSCRIBE = "transcribe"
STEP_DETECT_PAUSES = "detect_pauses"
STEP_BUILD_SEGMENTS = "build_segments"
STEP_DETECT_REPETITION = "detect_repetition"
STEP_PLAN_EDITS = "plan_edits"
STEP_REMAP_TIMELINE = "remap_timeline"
STEP_GENERATE_SUBTITLES = "generate_subtitles"
STEP_RENDER_VIDEO = "render_video"
STEP_GENERATE_REPORT = "generate_report"

ALL_STEPS = [
    STEP_EXTRACT_AUDIO,
    STEP_TRANSCRIBE,
    STEP_DETECT_PAUSES,
    STEP_BUILD_SEGMENTS,
    STEP_DETECT_REPETITION,
    STEP_PLAN_EDITS,
    STEP_REMAP_TIMELINE,
    STEP_GENERATE_SUBTITLES,
    STEP_RENDER_VIDEO,
    STEP_GENERATE_REPORT,
]

# ── 请求模型 ──

ALLOWED_EXTENSIONS = {".mp4", ".mov"}


class CreateJobRequest(BaseModel):
    """创建新任务的请求体。"""

    input_video_path: str = Field(..., description="Path to the input video file (mp4/mov)")
    output_dir: str = Field(..., description="Directory for all output artifacts")
    mode: str = Field(default="standard", description="Processing mode: standard, conservative, aggressive")

    @field_validator("mode")
    @classmethod
    def valid_mode(cls, v: str) -> str:
        if v not in ("standard", "conservative", "aggressive"):
            raise ValueError("mode must be 'standard', 'conservative', or 'aggressive'")
        return v


# ── 响应模型 ──

class CreateJobResponse(BaseModel):
    """创建任务后的响应。"""

    job_id: str = Field(..., description="Job UUID")
    status: str = Field(..., description="Job status")
    output_dir: str = Field(..., description="Output directory path")


class JobStatusResponse(BaseModel):
    """任务状态查询的响应。"""

    job_id: str = Field(..., description="Job UUID")
    status: str = Field(..., description="Job status")
    progress: float = Field(default=0.0, description="Progress fraction 0.0-1.0")
    current_step: str = Field(default="", description="Current pipeline step")
    error_message: str | None = Field(default=None, description="Error message if failed")
    created_at: str = Field(..., description="UTC ISO creation timestamp")
    updated_at: str = Field(..., description="UTC ISO last update timestamp")


class JobOutputsResponse(BaseModel):
    """任务输出查询的响应。"""

    status: str = Field(..., description="Job status")
    current_step: str = Field(default="", description="Current pipeline step")
    progress: float = Field(default=0.0, description="Progress fraction")
    error_message: str | None = Field(default=None, description="Error message if failed")
    edited_video_path: str | None = Field(default=None)
    transcript_path: str | None = Field(default=None)
    edit_decisions_path: str | None = Field(default=None)
    subtitles_path: str | None = Field(default=None)
    report_path: str | None = Field(default=None)