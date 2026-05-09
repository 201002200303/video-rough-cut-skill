"""Build cover and fixed overlay metadata for the final packaged video."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from core.utils import load_config
from core.utils import setup_logger
from schemas.models import Transcript
from schemas.models import VisualMetadata

logger = setup_logger(__name__)


def generate_visual_metadata(
    remapped_transcript: Transcript,
    output_path: Path,
    overrides: dict[str, Any] | None = None,
) -> VisualMetadata:
    """Create normalized visual metadata and write it as JSON."""
    cfg = load_config().get("visual_overlay", {})
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}

    date_label = str(overrides.get("date_label") or _today_label())
    cover_title = str(overrides.get("cover_title") or _default_cover_title(remapped_transcript, cfg))
    top_right_label = str(overrides.get("top_right_label") or _default_top_right_label(date_label, cfg))

    metadata = VisualMetadata(
        enabled=bool(overrides.get("enabled", cfg.get("enabled", True))),
        generate_cover=bool(overrides.get("generate_cover", cfg.get("generate_cover", True))),
        cover_title=_normalize_cover_title(cover_title),
        date_label=date_label,
        cover_subtitle=str(overrides.get("cover_subtitle") or cfg.get("default_cover_subtitle", "看盘笔记")),
        top_right_label=top_right_label,
        person_intro=str(overrides.get("person_intro") or cfg.get("person_intro", "")),
        disclaimer_lines=list(overrides.get("disclaimer_lines") or cfg.get("disclaimer_lines", [])),
        insert_cover_seconds=float(overrides.get("insert_cover_seconds", cfg.get("insert_cover_seconds", 0.0)) or 0.0),
        cover_frame_time=float(overrides.get("cover_frame_time", cfg.get("cover_frame_time", 0.5)) or 0.5),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(metadata.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Visual metadata generated: %s", output_path)
    return metadata


def load_visual_overrides(path: Path | None, cli_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load optional visual metadata JSON, then apply direct CLI overrides."""
    merged: dict[str, Any] = {}
    if path:
        merged.update(json.loads(path.read_text(encoding="utf-8")))
    for key, value in (cli_overrides or {}).items():
        if value is not None:
            merged[key] = value
    return merged


def _today_label() -> str:
    return datetime.now().strftime("%Y.%m.%d")


def _default_top_right_label(date_label: str, cfg: dict[str, Any]) -> str:
    suffix = str(cfg.get("default_top_right_suffix", "收评")).strip()
    digits = "".join(re.findall(r"\d+", date_label))
    short_date = digits[-4:] if len(digits) >= 4 else digits
    return f"{short_date} {suffix}".strip()


def _default_cover_title(transcript: Transcript, cfg: dict[str, Any]) -> str:
    configured = str(cfg.get("default_cover_title", "")).strip()
    text = _first_clean_segment_text(transcript)
    if not text:
        return configured or "今日看盘\n重点提醒"
    if len(text) <= 14:
        return text
    return text[:14]


def _first_clean_segment_text(transcript: Transcript) -> str:
    for segment in transcript.segments:
        text = re.sub(r"[，。！？、,.!?\s]+", "", segment.text or "")
        if len(text) >= 4:
            return text
    return ""


def _normalize_cover_title(title: str) -> str:
    cleaned = title.replace("\\n", "\n").strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines and cleaned:
        lines = [cleaned]
    if len(lines) == 1 and len(lines[0]) > 7:
        line = lines[0]
        midpoint = min(7, max(4, len(line) // 2))
        lines = [line[:midpoint], line[midpoint:]]
    return "\n".join(lines[:2])
