"""Pydantic models used by the video rough-cut pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class TranscriptWord(BaseModel):
    word: str = Field(..., description="Word text")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    timestamp_source: str = Field(default="estimated", description="provider or estimated")

    @field_validator("start")
    @classmethod
    def start_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("start must be >= 0")
        return value

    @field_validator("end")
    @classmethod
    def end_after_start(cls, value: float, info) -> float:
        if info.data.get("start") is not None and value <= info.data["start"]:
            raise ValueError("end must be > start")
        return value

    @field_validator("timestamp_source")
    @classmethod
    def valid_timestamp_source(cls, value: str) -> str:
        if value not in ("provider", "estimated"):
            raise ValueError("timestamp_source must be 'provider' or 'estimated'")
        return value


class TranscriptSegment(BaseModel):
    id: str = Field(..., description="Segment identifier")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    text: str = Field(..., description="Transcribed text with punctuation")
    words: list[TranscriptWord] = Field(default_factory=list, description="Word-level timestamps")

    @field_validator("start")
    @classmethod
    def start_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("start must be >= 0")
        return value

    @field_validator("end")
    @classmethod
    def end_after_start(cls, value: float, info) -> float:
        if info.data.get("start") is not None and value <= info.data["start"]:
            raise ValueError("end must be > start")
        return value


class Transcript(BaseModel):
    language: str = Field(default="zh", description="Language code")
    segments: list[TranscriptSegment] = Field(default_factory=list, description="Ordered transcript segments")


class SemanticSegment(BaseModel):
    segment_id: str = Field(..., description="Segment identifier")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    text: str = Field(..., description="Combined text of this segment")
    source_segment_ids: list[str] = Field(default_factory=list, description="Transcript segment IDs")

    @field_validator("start")
    @classmethod
    def start_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("start must be >= 0")
        return value

    @field_validator("end")
    @classmethod
    def end_after_start(cls, value: float, info) -> float:
        if info.data.get("start") is not None and value <= info.data["start"]:
            raise ValueError("end must be > start")
        return value


class UtteranceUnit(BaseModel):
    unit_id: str = Field(..., description="Utterance unit identifier")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    text: str = Field(..., description="Original text for this unit")
    analysis_text: str = Field(default="", description="Corrected text used for LLM analysis only")
    source_segment_ids: list[str] = Field(default_factory=list, description="Transcript segment IDs")
    words: list[TranscriptWord] = Field(default_factory=list, description="Provider word boundaries in this unit")
    timestamp_source: str = Field(default="estimated", description="provider or estimated")

    @field_validator("start")
    @classmethod
    def unit_start_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("start must be >= 0")
        return value

    @field_validator("end")
    @classmethod
    def unit_end_after_start(cls, value: float, info) -> float:
        if info.data.get("start") is not None and value <= info.data["start"]:
            raise ValueError("end must be > start")
        return value

    @field_validator("timestamp_source")
    @classmethod
    def unit_valid_timestamp_source(cls, value: str) -> str:
        if value not in ("provider", "estimated"):
            raise ValueError("timestamp_source must be 'provider' or 'estimated'")
        return value


class EditDecision(BaseModel):
    type: str = Field(..., description="Edit type: delete or compress_pause")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    reason: str = Field(..., description="Human-readable reason for this edit")
    source: str = Field(..., description="Decision source")
    target_duration: float | None = Field(default=None, description="Target duration after compression")
    confidence: float | None = Field(default=None, description="Confidence score 0.0-1.0")

    @field_validator("type")
    @classmethod
    def valid_type(cls, value: str) -> str:
        if value not in ("delete", "compress_pause"):
            raise ValueError("type must be 'delete' or 'compress_pause'")
        return value

    @field_validator("start")
    @classmethod
    def start_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("start must be >= 0")
        return value

    @field_validator("end")
    @classmethod
    def end_after_start(cls, value: float, info) -> float:
        if info.data.get("start") is not None and value <= info.data["start"]:
            raise ValueError("end must be > start")
        return value


class EditDecisionFile(BaseModel):
    edits: list[EditDecision] = Field(default_factory=list, description="Ordered edit decisions")
    review_needed: list[dict] = Field(default_factory=list, description="Uncertain items needing review")


class SkillInput(BaseModel):
    input_video_path: str = Field(..., description="Path to the input video file")
    output_dir: str = Field(..., description="Directory for all output artifacts")
    mode: str = Field(default="standard", description="Processing mode")
    visual_metadata_path: str | None = Field(default=None, description="Optional JSON file with cover and overlay metadata")
    cover_title: str | None = Field(default=None, description="Optional cover title override")
    date_label: str | None = Field(default=None, description="Optional cover date label override")
    cover_subtitle: str | None = Field(default=None, description="Optional cover subtitle override")
    top_right_label: str | None = Field(default=None, description="Optional top-right in-video label override")
    person_intro: str | None = Field(default=None, description="Optional bottom intro line override")
    insert_cover_seconds: float | None = Field(default=None, description="Optional cover intro duration")

    @field_validator("mode")
    @classmethod
    def valid_mode(cls, value: str) -> str:
        if value not in ("standard", "conservative", "aggressive"):
            raise ValueError("mode must be 'standard', 'conservative', or 'aggressive'")
        return value


class SkillOutput(BaseModel):
    edited_video_path: str = Field(..., description="Path to the edited video")
    transcript_path: str = Field(..., description="Path to transcript.json")
    edit_decisions_path: str = Field(..., description="Path to edit_decisions.json")
    subtitles_path: str = Field(..., description="Path to subtitles.ass")
    report_path: str = Field(..., description="Path to edit_report.md")
    visual_metadata_path: str | None = Field(default=None, description="Path to visual_metadata.json")
    visual_overlay_ass_path: str | None = Field(default=None, description="Path to visual_overlay.ass")
    cover_image_path: str | None = Field(default=None, description="Path to generated cover.png")


class VisualMetadata(BaseModel):
    enabled: bool = Field(default=True, description="Whether to add cover and in-video overlay packaging")
    generate_cover: bool = Field(default=True, description="Whether to generate cover image")
    cover_title: str = Field(default="今日看盘\n重点提醒", description="Large yellow cover title")
    date_label: str = Field(default="", description="Date label shown on cover")
    cover_subtitle: str = Field(default="看盘笔记", description="Small cover subtitle near date")
    top_right_label: str = Field(default="", description="Top-right in-video label")
    person_intro: str = Field(default="", description="Bottom intro line")
    disclaimer_lines: list[str] = Field(default_factory=list, description="Fixed bottom disclaimer lines")
    insert_cover_seconds: float = Field(default=0.0, description="Optional cover intro duration in seconds")
    cover_frame_time: float = Field(default=0.5, description="Video timestamp used as cover background")

    @field_validator("cover_title", "cover_subtitle", "date_label", "top_right_label", "person_intro")
    @classmethod
    def strip_visual_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("insert_cover_seconds", "cover_frame_time")
    @classmethod
    def visual_seconds_non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("visual timing values must be >= 0")
        return value
