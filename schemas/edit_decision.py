"""编辑决策 Pydantic 模型。"""

from pydantic import BaseModel, Field, field_validator


class EditDecision(BaseModel):
    """针对某时间范围的单条编辑决策。"""

    type: str = Field(..., description="Edit type: 'delete' or 'compress_pause'")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    reason: str = Field(..., description="Human-readable reason for this edit")
    source: str = Field(..., description="Decision source: 'rule' or 'llm'")
    target_duration: float | None = Field(default=None, description="Target duration after compression (seconds)")
    confidence: float | None = Field(default=None, description="Confidence score 0.0-1.0")

    @field_validator("type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in ("delete", "compress_pause"):
            raise ValueError("type must be 'delete' or 'compress_pause'")
        return v

    @field_validator("start")
    @classmethod
    def start_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("start must be >= 0")
        return v

    @field_validator("end")
    @classmethod
    def end_after_start(cls, v: float, info) -> float:
        if info.data.get("start") is not None and v <= info.data["start"]:
            raise ValueError("end must be > start")
        return v


class EditDecisionFile(BaseModel):
    """某任务的所有编辑决策集合。"""

    edits: list[EditDecision] = Field(default_factory=list, description="Ordered edit decisions")
    review_needed: list[dict] = Field(default_factory=list, description="Uncertain items needing human review")