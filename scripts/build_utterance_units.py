"""Build stable, numbered utterance units for semantic deletion."""

from __future__ import annotations

import json
from pathlib import Path

from core.utils import setup_logger
from schemas.models import Transcript, TranscriptWord, UtteranceUnit

logger = setup_logger(__name__)


def build_utterance_units(
    transcript: Transcript,
    output_path: Path | None = None,
    min_duration: float = 0.35,
    max_duration: float = 6.0,
    word_gap_split_threshold: float = 0.45,
) -> list[UtteranceUnit]:
    units: list[UtteranceUnit] = []
    for seg in transcript.segments:
        chunks = _word_chunks(seg.words, max_duration, word_gap_split_threshold) if seg.words else []
        if not chunks:
            duration = seg.end - seg.start
            if duration >= min_duration:
                units.append(
                    _unit(
                        len(units) + 1,
                        seg.start,
                        seg.end,
                        seg.text,
                        [seg.id],
                        [],
                        "estimated",
                    )
                )
            continue
        for chunk in chunks:
            start, end = chunk[0].start, chunk[-1].end
            if end - start < min_duration:
                continue
            text = _chunk_text(seg.text, seg.words, chunk)
            source = "provider" if all(w.timestamp_source == "provider" for w in chunk) else "estimated"
            units.append(_unit(len(units) + 1, start, end, text, [seg.id], chunk, source))

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps([u.model_dump() for u in units], ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Utterance units saved: %s (count=%d)", output_path, len(units))
    return units


def write_utterance_units(units: list[UtteranceUnit], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps([u.model_dump() for u in units], ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Utterance units saved: %s (count=%d)", output_path, len(units))


def _word_chunks(
    words: list[TranscriptWord],
    max_duration: float,
    word_gap_split_threshold: float,
) -> list[list[TranscriptWord]]:
    chunks: list[list[TranscriptWord]] = []
    current: list[TranscriptWord] = []
    for word in sorted(words, key=lambda w: (w.start, w.end)):
        if current:
            gap = word.start - current[-1].end
            duration = word.end - current[0].start
            if gap >= word_gap_split_threshold or duration > max_duration:
                chunks.append(current)
                current = []
        current.append(word)
    if current:
        chunks.append(current)
    return chunks


def _chunk_text(segment_text: str, segment_words: list[TranscriptWord], chunk: list[TranscriptWord]) -> str:
    if len(chunk) == len(segment_words) and chunk[0].start == segment_words[0].start and chunk[-1].end == segment_words[-1].end:
        return segment_text
    return "".join(w.word for w in chunk)


def _unit(
    idx: int,
    start: float,
    end: float,
    text: str,
    source_segment_ids: list[str],
    words: list[TranscriptWord],
    timestamp_source: str,
) -> UtteranceUnit:
    clean_text = text.strip()
    return UtteranceUnit(
        unit_id=f"u-{idx:04d}",
        start=round(start, 3),
        end=round(end, 3),
        text=clean_text,
        analysis_text=clean_text,
        source_segment_ids=source_segment_ids,
        words=words,
        timestamp_source=timestamp_source,
    )
