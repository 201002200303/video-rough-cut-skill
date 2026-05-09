"""LLM-based subtitle text correction without changing timestamps."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from core.utils import load_config, setup_logger
from providers.aliyun_qwen import AliyunQwenProvider
from schemas.models import Transcript, TranscriptSegment, UtteranceUnit

logger = setup_logger(__name__)


def correct_subtitle_text(
    transcript: Transcript,
    prompt_template_path: Path,
    reference_units: list[UtteranceUnit] | None = None,
) -> Transcript:
    cfg = load_config().get("subtitle_correction", {})
    if not bool(cfg.get("enabled", True)):
        return transcript
    max_segment_chars = int(cfg.get("max_segment_chars", 120))
    max_length_ratio = float(cfg.get("max_length_ratio", 1.6))
    min_similarity = float(cfg.get("min_similarity", 0.45))
    chunk_size = max(1, int(cfg.get("chunk_size", 12)))
    context_segments = max(0, int(cfg.get("context_segments", 1)))
    max_context_chars = int(cfg.get("max_context_chars", 80))
    provider = AliyunQwenProvider()
    prompt_template = prompt_template_path.read_text(encoding="utf-8")
    reference_by_segment_id = _reference_text_by_segment_id(reference_units or [])
    corrections = []
    try:
        for chunk_start, chunk in _chunks_with_start(transcript.segments, chunk_size):
            payload = {
                "segments": [
                    _segment_payload(
                        transcript.segments,
                        chunk_start + idx,
                        seg,
                        reference_by_segment_id,
                        max_segment_chars,
                        context_segments,
                        max_context_chars,
                    )
                    for idx, seg in enumerate(chunk)
                ]
            }
            prompt = f"{prompt_template}\n\n输入:\n{json.dumps(payload, ensure_ascii=False)}"
            result = provider.semantic_dedup(prompt)
            chunk_corrections = result.get("segments", [])
            if not isinstance(chunk_corrections, list):
                logger.warning("Subtitle correction returned invalid segments for a chunk; keeping that chunk original")
                continue
            corrections.extend(chunk_corrections)
    except Exception as exc:
        logger.warning("Subtitle correction failed; using original transcript text: %s", exc)
        return transcript

    text_by_id = {
        str(item.get("segment_id")): str(item.get("text", "")).strip()
        for item in corrections
        if isinstance(item, dict)
    }

    corrected_segments: list[TranscriptSegment] = []
    changed = 0
    rejected = 0
    for seg in transcript.segments:
        corrected = text_by_id.get(seg.id, "").strip()
        if _valid_correction(seg.text, corrected, max_length_ratio, min_similarity):
            text = corrected
            if text != seg.text:
                changed += 1
        else:
            if corrected:
                rejected += 1
            text = seg.text
        corrected_segments.append(
            TranscriptSegment(
                id=seg.id,
                start=seg.start,
                end=seg.end,
                text=text,
                words=seg.words,
            )
        )
    logger.info("Subtitle correction changed %d/%d segments", changed, len(corrected_segments))
    if rejected:
        logger.info("Subtitle correction rejected %d unsafe candidate(s)", rejected)
    return Transcript(language=transcript.language, segments=corrected_segments)


def _valid_correction(original: str, corrected: str, max_length_ratio: float, min_similarity: float) -> bool:
    if not corrected:
        return False
    original_len = max(1, len(original.strip()))
    corrected_len = len(corrected)
    if corrected_len > original_len * max_length_ratio:
        return False
    if corrected_len < original_len / max_length_ratio:
        return False
    similarity = SequenceMatcher(None, _normalize_text(original), _normalize_text(corrected)).ratio()
    if similarity < min_similarity:
        return False
    corrected_norm = _normalize_text(corrected)
    for phrase in _number_phrases(original):
        if phrase not in corrected_norm:
            return False
    return True


def _normalize_text(text: str) -> str:
    return "".join(ch for ch in text.strip().lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _number_phrases(text: str) -> list[str]:
    norm = _normalize_text(text)
    phrases = re.findall(r"[0-9一二三四五六七八九十百千万亿两零〇]{2,}", norm)
    return [phrase for phrase in phrases if not (len(phrase) == 2 and phrase.endswith("月"))]


def _segment_payload(
    segments: list[TranscriptSegment],
    index: int,
    seg: TranscriptSegment,
    reference_by_segment_id: dict[str, str],
    max_segment_chars: int,
    context_segments: int,
    max_context_chars: int,
) -> dict:
    payload = {
        "segment_id": seg.id,
        "start": seg.start,
        "end": seg.end,
        "text": seg.text[:max_segment_chars],
    }
    before = _context_text(segments[max(0, index - context_segments) : index], max_context_chars)
    after = _context_text(segments[index + 1 : index + 1 + context_segments], max_context_chars)
    if before:
        payload["context_before"] = before
    if after:
        payload["context_after"] = after
    reference_text = _reference_for_segment(seg.id, reference_by_segment_id)
    if reference_text and _valid_reference(seg.text, reference_text):
        payload["reference_text"] = reference_text[:max_segment_chars]
    return payload


def _context_text(segments: list[TranscriptSegment], max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    text = "".join(seg.text for seg in segments).strip()
    return text[-max_chars:] if len(text) > max_chars else text


def _reference_text_by_segment_id(units: list[UtteranceUnit]) -> dict[str, str]:
    refs: dict[str, list[str]] = {}
    for unit in units:
        reference_text = (unit.analysis_text or unit.text).strip()
        if not reference_text or reference_text == unit.text:
            continue
        for segment_id in unit.source_segment_ids:
            refs.setdefault(segment_id, []).append(reference_text)
    return {segment_id: "".join(parts).strip() for segment_id, parts in refs.items()}


def _reference_for_segment(segment_id: str, reference_by_segment_id: dict[str, str]) -> str:
    exact = reference_by_segment_id.get(segment_id, "")
    if exact:
        return exact
    prefix = ""
    best = ""
    for source_segment_id, reference_text in reference_by_segment_id.items():
        candidate_prefix = f"{source_segment_id}_part"
        if segment_id.startswith(candidate_prefix) and len(candidate_prefix) > len(prefix):
            prefix = candidate_prefix
            best = reference_text
    return best


def _valid_reference(original: str, reference_text: str) -> bool:
    original_norm = _normalize_text(original)
    reference_norm = _normalize_text(reference_text)
    if not original_norm or not reference_norm:
        return False
    ratio = SequenceMatcher(None, original_norm, reference_norm).ratio()
    return ratio >= 0.35 and len(reference_norm) <= max(1, len(original_norm)) * 2.0


def _chunks(items: list[TranscriptSegment], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _chunks_with_start(items: list[TranscriptSegment], size: int):
    for i in range(0, len(items), size):
        yield i, items[i : i + size]
