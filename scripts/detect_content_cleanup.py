"""检测口播中的低价值/幻听片段，生成可删除区间。"""

import json
from pathlib import Path

from core.config import load_config
from core.logging import setup_logger
from providers.aliyun_qwen import AliyunQwenProvider
from schemas.edit_decision import EditDecision
from schemas.transcript import Transcript

logger = setup_logger(__name__)


def detect_content_cleanup(
    transcript: Transcript,
    prompt_template_path: Path,
    min_confidence_to_delete: float | None = None,
    max_segment_chars: int | None = None,
    review_on_uncertain: bool | None = None,
    max_auto_delete_duration: float | None = None,
    boundary_guard: float | None = None,
    auto_delete_enabled: bool | None = None,
) -> tuple[list[EditDecision], list[dict]]:
    """识别明显语气词、废话尾巴、ASR 幻听等低价值片段。"""
    cfg = load_config().get("content_cleanup", {})
    min_confidence_to_delete = float(
        min_confidence_to_delete
        if min_confidence_to_delete is not None
        else cfg.get("min_confidence_to_delete", 0.92)
    )
    max_segment_chars = int(
        max_segment_chars if max_segment_chars is not None else cfg.get("max_segment_chars", 300)
    )
    review_on_uncertain = bool(
        review_on_uncertain if review_on_uncertain is not None else cfg.get("review_on_uncertain", True)
    )
    max_auto_delete_duration = float(
        max_auto_delete_duration
        if max_auto_delete_duration is not None
        else cfg.get("max_auto_delete_duration", 3.0)
    )
    boundary_guard = float(
        boundary_guard if boundary_guard is not None else cfg.get("boundary_guard", 0.25)
    )
    auto_delete_enabled = bool(
        auto_delete_enabled if auto_delete_enabled is not None else cfg.get("auto_delete_enabled", False)
    )

    provider = AliyunQwenProvider()
    prompt_template = prompt_template_path.read_text(encoding="utf-8")
    payload = {"segments": [_segment_payload(seg, max_segment_chars) for seg in transcript.segments]}
    result = provider.semantic_dedup(f"{prompt_template}\n\n输入:\n{json.dumps(payload, ensure_ascii=False)}")

    edits: list[EditDecision] = []
    review_needed: list[dict] = []
    seg_by_id = {seg.id: seg for seg in transcript.segments}
    for item in result.get("delete_ranges", []):
        seg_id = str(item.get("segment_id", ""))
        start = float(item.get("start", 0.0))
        end = float(item.get("end", 0.0))
        confidence = float(item.get("confidence", 0.0))
        reason = str(item.get("reason", "content_cleanup"))
        seg = seg_by_id.get(seg_id)
        if not seg or end <= start:
            continue
        if not _range_matches_word_boundary(seg, start, end):
            review_needed.append(_review_item(seg, start, end, confidence, reason, "range_not_on_word_boundary"))
            continue
        if not auto_delete_enabled:
            review_needed.append(_review_item(seg, start, end, confidence, reason, "cleanup_auto_delete_disabled"))
            continue
        if end - start > max_auto_delete_duration:
            review_needed.append(_review_item(seg, start, end, confidence, reason, "cleanup_delete_too_long"))
            continue
        guarded_start, guarded_end = (
            (start, end)
            if _range_covers_segment(seg, start, end)
            else _apply_boundary_guard(start, end, boundary_guard)
        )
        if guarded_end <= guarded_start:
            review_needed.append(_review_item(seg, start, end, confidence, reason, "cleanup_delete_too_short_after_guard"))
            continue
        if confidence >= min_confidence_to_delete:
            edits.append(
                EditDecision(
                    type="delete",
                    start=guarded_start,
                    end=guarded_end,
                    reason=f"{reason}；已向内收缩 {boundary_guard:.2f}s 避免切掉相邻尾音",
                    source="content_cleanup",
                    confidence=confidence,
                )
            )
        elif review_on_uncertain:
            review_needed.append(_review_item(seg, start, end, confidence, reason, "low_confidence_cleanup"))

    for item in result.get("review_needed", []):
        review_needed.append(item if isinstance(item, dict) else {"type": "content_cleanup_review", "detail": str(item)})
    logger.info("Content cleanup edits=%d review_needed=%d", len(edits), len(review_needed))
    return edits, review_needed


def _segment_payload(seg, max_segment_chars: int) -> dict:
    return {
        "segment_id": seg.id,
        "start": seg.start,
        "end": seg.end,
        "text": seg.text[:max_segment_chars],
        "words": [
            {"word": w.word, "start": w.start, "end": w.end}
            for w in seg.words
        ],
    }


def _range_matches_word_boundary(seg, start: float, end: float) -> bool:
    starts = {round(w.start, 3) for w in seg.words}
    ends = {round(w.end, 3) for w in seg.words}
    return round(start, 3) in starts and round(end, 3) in ends


def _apply_boundary_guard(start: float, end: float, guard: float) -> tuple[float, float]:
    """自动删除边界向内收缩，降低估算时间戳切掉前后语音的风险。"""
    duration = end - start
    max_guard = max(0.0, (duration - 0.25) / 2)
    actual_guard = min(max(0.0, guard), max_guard)
    return start + actual_guard, end - actual_guard


def _range_covers_segment(seg, start: float, end: float) -> bool:
    """整段低价值时直接删除整段，避免内缩后残留半个语气词/欢迎词。"""
    return start <= seg.start + 0.02 and end >= seg.end - 0.02


def _review_item(seg, start: float, end: float, confidence: float, reason: str, item_type: str) -> dict:
    return {
        "type": item_type,
        "segment_id": seg.id,
        "segment_text_preview": seg.text[:80],
        "start": start,
        "end": end,
        "confidence": confidence,
        "reason": reason,
    }
