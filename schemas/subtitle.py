"""字幕数据 Pydantic 模型（ASS 生成）。"""

from pydantic import BaseModel, Field, field_validator


class SubtitleEvent(BaseModel):
    """ASS 格式的单条字幕事件。"""

    id: str = Field(..., description="Subtitle event identifier")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    text: str = Field(..., description="Subtitle text content")
    style: str = Field(default="Default", description="ASS style name")

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


class SubtitleData(BaseModel):
    """ASS 生成的字幕事件集合。"""

    events: list[SubtitleEvent] = Field(default_factory=list, description="Ordered subtitle events")
    total_duration: float = Field(..., description="Total duration of the edited video in seconds")