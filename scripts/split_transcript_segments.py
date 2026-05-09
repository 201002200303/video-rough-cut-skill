"""Split ASR transcript segments on long provider word gaps."""

from __future__ import annotations

import json
from pathlib import Path

from core.utils import setup_logger
from schemas.models import Transcript
from schemas.models import TranscriptSegment
from schemas.models import TranscriptWord

logger = setup_logger(__name__)


def split_transcript_segments_on_word_gaps(
    transcript: Transcript,
    output_path: Path | None = None,
    word_gap_threshold: float = 0.65,
    min_segment_duration: float = 0.35,
    min_segment_chars: int = 2,
) -> Transcript:
    """Split long ASR segments before semantic analysis sees them."""
    segments: list[TranscriptSegment] = []
    split_count = 0
    for seg in transcript.segments:
        chunks = _split_words(seg.words, word_gap_threshold) if _can_split(seg.words) else []
        valid_chunks = [
            chunk
            for chunk in chunks
            if _chunk_duration(chunk) >= min_segment_duration and len(_chunk_text(chunk)) >= min_segment_chars
        ]
        if len(valid_chunks) <= 1:
            segments.append(seg)
            continue
        split_count += len(valid_chunks) - 1
        for idx, chunk in enumerate(valid_chunks, start=1):
            segments.append(
                TranscriptSegment(
                    id=f"{seg.id}_part{idx}",
                    start=round(chunk[0].start, 3),
                    end=round(chunk[-1].end, 3),
                    text=_chunk_text(chunk),
                    words=chunk,
                )
            )

    out = Transcript(language=transcript.language, segments=segments)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(out.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Transcript segment split complete: original=%d output=%d split_count=%d", len(transcript.segments), len(out.segments), split_count)
    return out


def _can_split(words: list[TranscriptWord]) -> bool:
    return len(words) >= 2 and all(word.timestamp_source == "provider" for word in words)


def _split_words(words: list[TranscriptWord], threshold: float) -> list[list[TranscriptWord]]:
    chunks: list[list[TranscriptWord]] = []
    current: list[TranscriptWord] = []
    ordered = sorted(words, key=lambda w: (w.start, w.end))
    for word in ordered:
        if current and word.start - current[-1].end >= threshold:
            chunks.append(current)
            current = []
        current.append(word)
    if current:
        chunks.append(current)
    return chunks


def _chunk_duration(words: list[TranscriptWord]) -> float:
    return words[-1].end - words[0].start


def _chunk_text(words: list[TranscriptWord]) -> str:
    return "".join(word.word for word in words).strip()
