"""从 ASR Transcript 构建不可变 SourceWord 列表。"""

from __future__ import annotations

import json
from pathlib import Path

from core.utils import setup_logger
from schemas.models import SourceWord, Transcript, TranscriptSegment, TranscriptWord

logger = setup_logger(__name__)


def enrich_transcript_with_word_ids(transcript: Transcript, source_words: list[SourceWord]) -> Transcript:
    """与 build_source_words 相同的展平顺序，为每个 TranscriptWord 挂上 SourceWord.word_id。"""
    idx = 0
    new_segments: list[TranscriptSegment] = []
    for seg in transcript.segments:
        seg_words = seg.words if seg.words else _estimate_words_from_segment(seg)
        new_words: list[TranscriptWord] = []
        for w in seg_words:
            wid: str | None = None
            if idx < len(source_words):
                sw = source_words[idx]
                if sw.char != w.word:
                    logger.warning(
                        "enrich: char mismatch at index %d seg=%s transcript=%r source=%r",
                        idx,
                        seg.id,
                        w.word,
                        sw.char,
                    )
                wid = sw.word_id
                idx += 1
            new_words.append(
                TranscriptWord(
                    word=w.word,
                    start=w.start,
                    end=w.end,
                    timestamp_source=w.timestamp_source,
                    word_id=wid,
                )
            )
        new_segments.append(
            TranscriptSegment(id=seg.id, start=seg.start, end=seg.end, text=seg.text, words=new_words)
        )
    if idx != len(source_words):
        logger.warning(
            "enrich_transcript_with_word_ids: walked %d words, source_words has %d",
            idx,
            len(source_words),
        )
    return Transcript(language=transcript.language, segments=new_segments)


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
