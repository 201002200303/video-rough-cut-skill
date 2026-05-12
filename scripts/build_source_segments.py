"""从 Transcript + SourceWords 构建不可变 SourceSegment 列表。"""

from __future__ import annotations

import json
from pathlib import Path

from core.utils import setup_logger
from schemas.models import SourceSegment, SourceWord, Transcript

logger = setup_logger(__name__)


def build_source_segments(
    transcript: Transcript,
    source_words: list[SourceWord],
    output_path: Path | None = None,
) -> list[SourceSegment]:
    """为每个 transcript segment 创建对应的 SourceSegment。

    SourceSegment 是不可变的——切分前原始 ASR segment 的快照。
    """
    # 按 segment_id 索引 source words
    words_by_segment: dict[str, list[SourceWord]] = {}
    for w in source_words:
        words_by_segment.setdefault(w.segment_id, []).append(w)

    segments: list[SourceSegment] = []
    for seg in transcript.segments:
        sw = words_by_segment.get(seg.id, [])
        segments.append(
            SourceSegment(
                segment_id=seg.id,
                word_ids=[w.word_id for w in sw],
                text=seg.text,
                start=seg.start,
                end=seg.end,
                split_reason="asr_original",
            )
        )

    logger.info("Built %d source segments", len(segments))

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps([s.model_dump() for s in segments], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return segments
