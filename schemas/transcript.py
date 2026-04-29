"""转写数据 Pydantic 模型（ASR 输出）。"""

from pydantic import BaseModel, Field, field_validator


class TranscriptWord(BaseModel):
    """带时间戳的单个词。"""

    word: str = Field(..., description="Word text")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    timestamp_source: str = Field(default="estimated", description="provider 或 estimated")

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

    @field_validator("timestamp_source")
    @classmethod
    def valid_timestamp_source(cls, v: str) -> str:
        if v not in ("provider", "estimated"):
            raise ValueError("timestamp_source must be 'provider' or 'estimated'")
        return v


class TranscriptSegment(BaseModel):
    """转写中带时间戳和文本的单个片段。"""

    id: str = Field(..., description="Segment identifier")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    text: str = Field(..., description="Transcribed text with punctuation")
    words: list[TranscriptWord] = Field(default_factory=list, description="Word-level timestamps")

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


class Transcript(BaseModel):
    """ASR 输出的完整转写数据。"""

    language: str = Field(default="zh", description="Language code")
    segments: list[TranscriptSegment] = Field(default_factory=list, description="Ordered transcript segments")