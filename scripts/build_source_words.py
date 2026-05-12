"""从 ASR Transcript 构建不可变 SourceWord 列表。"""

from __future__ import annotations

import json
from pathlib import Path

from core.utils import setup_logger
from schemas.models import SourceWord, Transcript

logger = setup_logger(__name__)


def build_source_words(
    transcript: Transcript,
    output_path: Path | None = None,
) -> list[SourceWord]:
    """将 Transcript.segments[*].words 展平为全局编号的 SourceWord 列表。

    每个 SourceWord 是 ASR 输出的不可变事实单元，后续所有阶段只读。
    """
    words: list[SourceWord] = []
    word_idx = 0

    for seg in transcript.segments:
        seg_words = seg.words if seg.words else _estimate_words_from_segment(seg)
        for w in seg_words:
            word_idx += 1
            words.append(
                SourceWord(
                    word_id=f"w-{word_idx:04d}",
                    char=w.word,
                    start=w.start,
                    end=w.end,
                    timestamp_source=w.timestamp_source,
                    segment_id=seg.id,
                    provider="funasr" if w.timestamp_source == "provider" else "aliyun",
                )
            )

    logger.info("Built %d source words from %d segments", len(words), len(transcript.segments))

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps([w.model_dump() for w in words], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return words


def _estimate_words_from_segment(seg) -> list:
    """Fallback: 当 segment 没有 word 级时间戳时，按字符均分时长。"""
    from schemas.models import TranscriptWord

    text = seg.text.strip()
    if not text:
        return []
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return []
    duration = seg.end - seg.start
    char_duration = duration / len(chars)
    return [
        TranscriptWord(
            word=ch,
            start=round(seg.start + i * char_duration, 3),
            end=round(seg.start + (i + 1) * char_duration, 3),
            timestamp_source="estimated",
        )
        for i, ch in enumerate(chars)
    ]
