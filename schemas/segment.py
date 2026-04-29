"""语义段 Pydantic 模型。"""

from pydantic import BaseModel, Field, field_validator


class SemanticSegment(BaseModel):
    """由转写和停顿检测生成的语义段。"""

    segment_id: str = Field(..., description="Segment identifier")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    text: str = Field(..., description="Combined text of this segment")
    source_segment_ids: list[str] = Field(
        default_factory=list,
        description="Transcript segment IDs composing this segment",
    )

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