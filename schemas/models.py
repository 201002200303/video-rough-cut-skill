"""Pydantic models used by the video rough-cut pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TranscriptWord(BaseModel):
    word: str = Field(..., description="Word text")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    timestamp_source: str = Field(default="estimated", description="provider or estimated")
    word_id: str | None = Field(
        default=None,
        description="Optional global word id (w-0001) aligned with SourceWord after enrich; used for subtitle patch routing",
    )

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


# ═══════════════════════════════════════════════════════════════════
# V2.5 模型 — 不可变事实层 + 结构化补丁
# ═══════════════════════════════════════════════════════════════════


class SourceWord(BaseModel):
    """Immutable word-level timestamp from ASR. Never overwritten after creation."""

    word_id: str = Field(..., description="Globally unique word identifier, e.g. w-0001")
    char: str = Field(..., description="ASR original character or minimal word unit")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    confidence: float | None = Field(default=None, description="ASR confidence 0.0-1.0")
    segment_id: str = Field(..., description="Source segment id this word belongs to")
    timestamp_source: str = Field(default="provider", description="provider or estimated")
    provider: str = Field(default="funasr", description="ASR provider name")

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


class SourceSegment(BaseModel):
    """Immutable segment built from source words. Used for window construction."""

    segment_id: str = Field(..., description="Segment identifier")
    word_ids: list[str] = Field(default_factory=list, description="Source word IDs in this segment")
    text: str = Field(..., description="Concatenated source word chars")
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    split_reason: str = Field(default="pause_gap", description="Why this segment was split")

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


class DisplayPatch(BaseModel):
    """Subtitle-only text correction. Never affects video timeline."""

    patch_id: str = Field(..., description="Unique patch identifier")
    type: Literal["replace_display", "replace_display_span", "insert_display", "delete_display_noise"] = Field(
        ..., description="Patch type"
    )
    word_ids: list[str] = Field(default_factory=list, description="Affected source word IDs")
    after_word_id: str | None = Field(default=None, description="Insertion point for insert_display")
    from_text: str = Field(default="", description="Original text that matches source words")
    to_text: str = Field(default="", description="Replacement display text")
    confidence: float = Field(..., description="Confidence 0.0-1.0")
    evidence: dict = Field(default_factory=dict, description="Evidence for this correction")
    affects_timeline: bool = Field(default=False, description="Always False for display patches")

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return value


class DeletionCandidate(BaseModel):
    """Timeline deletion proposal. Must bind to real source word IDs."""

    candidate_id: str = Field(..., description="Unique candidate identifier")
    window_id: str = Field(..., description="Parent window ID")
    type: Literal[
        "fast_repetition", "false_start", "redundant_restatement", "incomplete_fragment", "filler_phrase"
    ] = Field(..., description="Deletion type")
    word_ids: list[str] = Field(..., description="Source word IDs to delete")
    delete_text_original: str = Field(..., description="Original text being deleted")
    delete_text_corrected_view: str = Field(default="", description="Corrected-view text being deleted")
    before_text_corrected_view: str = Field(default="", description="Text before deletion in corrected view")
    after_text_corrected_view: str = Field(default="", description="Text after deletion in corrected view")
    reason: str = Field(..., description="Human-readable reason")
    confidence: float = Field(..., description="Confidence 0.0-1.0")

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return value


class GlobalContext(BaseModel):
    """Output of global semantic analysis phase.

    Only provides information that per-segment prompts cannot self-derive:
    - summary: high-level content anchor for downstream disambiguation
    - topic: domain anchor for disambiguation
    - speaker: ASR-inconsistent self-reference variants → canonical
    - canonical_terms: terms that appear multiple times with inconsistent ASR output → canonical
    """

    summary: str = Field(default="", description="2-3 sentence summary of the full transcript: core thesis, main topics, speaker stance")
    topic: str = Field(default="", description="Video topic (domain anchor)")
    speaker_aliases: list[str] = Field(default_factory=list, description="Speaker name variants from ASR")
    canonical_speaker_name: str = Field(default="", description="Most likely standard speaker name, empty if not applicable")
    canonical_speaker_confidence: float = Field(default=0.0, description="Confidence for canonical_speaker_name, 0.0-1.0")
    canonical_terms: list[dict] = Field(
        default_factory=list,
        description="Terms with inconsistent ASR output across segments: {canonical, variants, evidence, confidence}",
    )


class SegmentIssue(BaseModel):
    """Per-segment issue flag from screening phase."""

    segment_id: str = Field(..., description="Segment identifier")
    issue_types: list[str] = Field(
        default_factory=list,
        description="Issue categories: asr_homophone_error, speaker_name_error, domain_term_error, "
        "missing_char, extra_noise_char, fast_repetition, false_start, semantic_restatement, "
        "filler_heavy, uncertain",
    )
    priority: Literal["high", "medium", "low"] = Field(default="medium", description="Issue priority")
    evidence: str = Field(default="", description="Evidence description for LLM screening")


class Window(BaseModel):
    """Five-segment analysis window for LLM correction or dedup phase.

    phase 字段区分窗口用途：
    - "correction" → 只做 ASR 纠错（DisplayPatch），不改时间轴
    - "dedup"      → 只做口误删除（DeletionCandidate），不改字幕
    """

    window_id: str = Field(..., description="Window identifier")
    phase: str = Field(default="correction", description="correction or dedup")
    target_segment_ids: list[str] = Field(..., description="Segments that may be edited")
    left_context_segment_ids: list[str] = Field(default_factory=list, description="Read-only left context")
    right_context_segment_ids: list[str] = Field(default_factory=list, description="Read-only right context")
    allowed_edit_segment_ids: list[str] = Field(default_factory=list, description="Segments where edits are permitted")

    @property
    def all_segment_ids(self) -> list[str]:
        return self.left_context_segment_ids + self.target_segment_ids + self.right_context_segment_ids


class CorrectionCandidate(BaseModel):
    """Raw LLM output from window correction phase, before validation."""

    window_id: str = Field(..., description="Parent window ID")
    type: Literal["replace_display", "replace_display_span", "insert_display", "delete_display_noise"] = Field(
        ..., description="Correction type"
    )
    word_ids: list[str] = Field(default_factory=list, description="Affected source word IDs")
    after_word_id: str | None = Field(default=None, description="Insertion point for insert_display")
    from_text: str = Field(default="", description="Original text")
    to_text: str = Field(default="", description="Correction text")
    confidence: float = Field(..., description="LLM confidence 0.0-1.0")
    evidence: dict = Field(default_factory=dict, description="LLM-provided evidence")

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return value



class ValidatedPatchFile(BaseModel):
    """Output of the correction validation phase."""

    accepted: list[DisplayPatch] = Field(default_factory=list, description="Validated display patches")
    rejected: list[dict] = Field(default_factory=list, description="Rejected patches with failure reasons")


class ValidatedDeletionFile(BaseModel):
    """Output of the deletion validation phase."""

    accepted: list[DeletionCandidate] = Field(default_factory=list, description="Validated deletion candidates")
    rejected: list[dict] = Field(default_factory=list, description="Rejected candidates with failure reasons")


class SegmentIssueFile(BaseModel):
    """Output of the segment issue screening phase."""

    issues: list[SegmentIssue] = Field(default_factory=list, description="Flagged segment issues")


class WindowFile(BaseModel):
    """Output of the window building phase."""

    windows: list[Window] = Field(default_factory=list, description="Built analysis windows")
