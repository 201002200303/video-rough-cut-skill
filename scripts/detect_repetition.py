"""基于 LLM 的语义重复检测。"""

import json
from pathlib import Path

from core.utils import load_config
from core.utils import setup_logger
from providers.aliyun_qwen import AliyunQwenProvider
from schemas.models import EditDecision
from schemas.models import Transcript
from schemas.models import TranscriptSegment

logger = setup_logger(__name__)


def detect_repetition(
    semantic_segments: list[dict],
    prompt_template_path: Path,
    semantic_window_seconds: float | None = None,
    min_confidence_to_delete: float | None = None,
    context_window_segments: int | None = None,
    max_segment_chars: int | None = None,
    review_on_uncertain: bool | None = None,
    max_auto_delete_duration: float | None = None,
    transcript: Transcript | None = None,
    local_prompt_template_path: Path | None = None,
) -> tuple[list[EditDecision], list[dict]]:
    """检测近邻语义重复片段并生成删除编辑决策。"""
    cfg = load_config().get("dedup", {})
    semantic_window_seconds = float(
        semantic_window_seconds if semantic_window_seconds is not None else cfg.get("semantic_window_seconds", 90.0)
    )
    min_confidence_to_delete = float(
        min_confidence_to_delete if min_confidence_to_delete is not None else cfg.get("similarity_threshold", 0.85)
    )
    context_window_segments = int(
        context_window_segments if context_window_segments is not None else cfg.get("context_window_segments", 3)
    )
    max_segment_chars = int(max_segment_chars if max_segment_chars is not None else cfg.get("max_segment_chars", 500))
    review_on_uncertain = bool(
        review_on_uncertain if review_on_uncertain is not None else cfg.get("review_on_uncertain", True)
    )
    max_auto_delete_duration = float(
        max_auto_delete_duration
        if max_auto_delete_duration is not None
        else cfg.get("max_auto_delete_duration", 4.0)
    )
    enable_local_refine = bool(cfg.get("enable_local_refine", True))
    local_refine_max_delete_duration = float(cfg.get("local_refine_max_delete_duration", 3.0))
    local_refine_min_confidence = float(cfg.get("local_refine_min_confidence", min_confidence_to_delete))
    local_refine_boundary_guard = float(cfg.get("local_refine_boundary_guard", 0.08))
    local_refine_max_total = float(
        cfg.get("local_refine_max_total_delete_duration_per_semantic_segment", 5.0)
    )
    local_refine_review_items = bool(cfg.get("local_refine_review_items", True))
    local_refine_max_review_segments = int(cfg.get("local_refine_max_review_segments", 8))
    local_refine_allow_multiple_ranges = bool(cfg.get("local_refine_allow_multiple_ranges_per_segment", False))
    local_refine_min_remaining_fragment_chars = int(cfg.get("local_refine_min_remaining_fragment_chars", 4))
    provider = AliyunQwenProvider()
    review_needed: list[dict] = []
    edits: list[EditDecision] = []
    emitted_delete_ids: set[str] = set()
    refined_review_segment_ids: set[str] = set()
    # 建立 segment_id -> 原始 segment 的映射，用于 review_needed 可读信息
    seg_by_id: dict[str, dict] = {s["segment_id"]: s for s in semantic_segments}
    prompt_template = prompt_template_path.read_text(encoding="utf-8")

    for i, seg in enumerate(semantic_segments):
        window = []
        start_idx = max(0, i - context_window_segments)
        for cand in semantic_segments[start_idx : i + 1]:
            if seg["start"] - cand["start"] <= semantic_window_seconds:
                window.append(_trim_segment_text(cand, max_segment_chars))
        if len(window) <= 1:
            continue
        prompt = _build_prompt(prompt_template, window)
        result = provider.semantic_dedup(prompt)
        for item in result.get("duplicate_groups", []):
            keep_id = item.get("keep_segment_id")
            delete_ids = item.get("delete_segment_ids", [])
            reason = item.get("reason", "semantic_dedup")
            conf = float(item.get("confidence", 0.0))
            for d_id in delete_ids:
                if d_id in emitted_delete_ids:
                    continue
                target = next((x for x in window if x["segment_id"] == d_id), None)
                if not target:
                    continue
                duration = float(target["end"]) - float(target["start"])
                if duration > max_auto_delete_duration:
                    refined_edits, refined_reviews = _refine_long_duplicate_candidate(
                        provider=provider,
                        transcript=transcript,
                        semantic_segment=seg_by_id.get(d_id, target),
                        keep_segment=seg_by_id.get(keep_id, {}),
                        reason=reason,
                        confidence=conf,
                        enabled=enable_local_refine,
                        prompt_template_path=local_prompt_template_path
                        or prompt_template_path.parent / "local_semantic_dedup.md",
                        min_confidence=local_refine_min_confidence,
                        max_delete_duration=local_refine_max_delete_duration,
                        boundary_guard=local_refine_boundary_guard,
                        max_total_delete_duration=local_refine_max_total,
                        allow_multiple_ranges_per_segment=local_refine_allow_multiple_ranges,
                        min_remaining_fragment_chars=local_refine_min_remaining_fragment_chars,
                    )
                    edits.extend(refined_edits)
                    review_type = "duplicate_long_refined" if refined_edits else "duplicate_delete_too_long"
                    review_needed.append(
                        {
                            "type": review_type,
                            "segment_id": d_id,
                            "segment_text_preview": str(seg_by_id.get(d_id, {}).get("text", ""))[:80],
                            "keep_segment_id": keep_id,
                            "keep_text_preview": str(seg_by_id.get(keep_id, {}).get("text", ""))[:80],
                            "start": target["start"],
                            "end": target["end"],
                            "duration": duration,
                            "confidence": conf,
                            "reason": reason,
                            "refined_delete_count": len(refined_edits),
                        }
                    )
                    review_needed.extend(refined_reviews)
                    continue
                if conf >= min_confidence_to_delete:
                    emitted_delete_ids.add(d_id)
                    edits.append(
                        EditDecision(
                            type="delete",
                            start=target["start"],
                            end=target["end"],
                            reason=reason,
                            source="semantic_dedup",
                            confidence=conf,
                        )
                    )
                elif review_on_uncertain:
                    del_seg = seg_by_id.get(d_id, {})
                    keep_seg = seg_by_id.get(keep_id, {})
                    review_needed.append(
                        {
                            "type": "duplicate_low_confidence",
                            "segment_id": d_id,
                            "segment_text_preview": str(del_seg.get("text", ""))[:80],
                            "keep_segment_id": keep_id,
                            "keep_text_preview": str(keep_seg.get("text", ""))[:80],
                            "confidence": conf,
                            "reason": reason,
                        }
                    )
        normalized_reviews = _normalize_review_needed(result.get("review_needed", []), seg_by_id)
        if local_refine_review_items and len(refined_review_segment_ids) < local_refine_max_review_segments:
            refined_edits, refined_reviews, used_ids = _refine_review_needed_segments(
                provider=provider,
                transcript=transcript,
                normalized_reviews=normalized_reviews,
                seg_by_id=seg_by_id,
                refined_segment_ids=refined_review_segment_ids,
                max_segments=local_refine_max_review_segments,
                prompt_template_path=local_prompt_template_path
                or prompt_template_path.parent / "local_semantic_dedup.md",
                min_confidence=local_refine_min_confidence,
                max_delete_duration=local_refine_max_delete_duration,
                boundary_guard=local_refine_boundary_guard,
                max_total_delete_duration=local_refine_max_total,
                allow_multiple_ranges_per_segment=local_refine_allow_multiple_ranges,
                min_remaining_fragment_chars=local_refine_min_remaining_fragment_chars,
            )
            edits.extend(refined_edits)
            normalized_reviews.extend(refined_reviews)
            refined_review_segment_ids.update(used_ids)
        review_needed.extend(normalized_reviews)
    logger.info("Semantic dedup edits=%d review_needed=%d", len(edits), len(review_needed))
    return edits, review_needed


def _refine_review_needed_segments(
    provider: AliyunQwenProvider,
    transcript: Transcript | None,
    normalized_reviews: list[dict],
    seg_by_id: dict[str, dict],
    refined_segment_ids: set[str],
    max_segments: int,
    prompt_template_path: Path,
    min_confidence: float,
    max_delete_duration: float,
    boundary_guard: float,
    max_total_delete_duration: float,
    allow_multiple_ranges_per_segment: bool,
    min_remaining_fragment_chars: int,
) -> tuple[list[EditDecision], list[dict], set[str]]:
    edits: list[EditDecision] = []
    reviews: list[dict] = []
    used_ids: set[str] = set()
    for item in normalized_reviews:
        if len(refined_segment_ids | used_ids) >= max_segments:
            break
        seg_id = str(item.get("segment_id") or "")
        if not seg_id or seg_id in refined_segment_ids or seg_id in used_ids:
            continue
        semantic_segment = seg_by_id.get(seg_id)
        if not semantic_segment:
            continue
        refined_edits, refined_reviews = _refine_long_duplicate_candidate(
            provider=provider,
            transcript=transcript,
            semantic_segment=semantic_segment,
            keep_segment={},
            reason=f"provider review item local refine: {item.get('detail', item.get('reason', 'review_needed'))}",
            confidence=float(item.get("confidence") or 0.0),
            enabled=True,
            prompt_template_path=prompt_template_path,
            min_confidence=min_confidence,
            max_delete_duration=max_delete_duration,
            boundary_guard=boundary_guard,
            max_total_delete_duration=max_total_delete_duration,
            allow_multiple_ranges_per_segment=allow_multiple_ranges_per_segment,
            min_remaining_fragment_chars=min_remaining_fragment_chars,
        )
        used_ids.add(seg_id)
        edits.extend(refined_edits)
        reviews.append(
            {
                "type": "provider_review_refined" if refined_edits else "provider_review_refine_no_edit",
                "segment_id": seg_id,
                "segment_text_preview": str(semantic_segment.get("text", ""))[:80],
                "refined_delete_count": len(refined_edits),
                "reason": item.get("reason", item.get("detail", "review_needed")),
            }
        )
        reviews.extend(refined_reviews)
    return edits, reviews, used_ids


def _refine_long_duplicate_candidate(
    provider: AliyunQwenProvider,
    transcript: Transcript | None,
    semantic_segment: dict,
    keep_segment: dict,
    reason: str,
    confidence: float,
    enabled: bool,
    prompt_template_path: Path,
    min_confidence: float,
    max_delete_duration: float,
    boundary_guard: float,
    max_total_delete_duration: float,
    allow_multiple_ranges_per_segment: bool,
    min_remaining_fragment_chars: int,
) -> tuple[list[EditDecision], list[dict]]:
    if not enabled:
        return [], [_local_review(semantic_segment, "local_refine_disabled", reason, confidence)]
    if transcript is None:
        return [], [_local_review(semantic_segment, "local_refine_missing_transcript", reason, confidence)]
    if not prompt_template_path.exists():
        return [], [_local_review(semantic_segment, "local_refine_prompt_missing", reason, confidence)]

    source_ids = set(semantic_segment.get("source_segment_ids", []))
    candidate_segments = [seg for seg in transcript.segments if seg.id in source_ids]
    if not candidate_segments:
        return [], [_local_review(semantic_segment, "local_refine_no_source_segments", reason, confidence)]
    if not all(_segment_has_provider_words(seg) for seg in candidate_segments):
        return [], [_local_review(semantic_segment, "local_refine_requires_provider_timestamps", reason, confidence)]

    payload = {
        "duplicate_candidate": {
            "segment_id": semantic_segment.get("segment_id"),
            "start": semantic_segment.get("start"),
            "end": semantic_segment.get("end"),
            "text": semantic_segment.get("text"),
            "reason": reason,
            "confidence": confidence,
        },
        "keep_segment": {
            "segment_id": keep_segment.get("segment_id"),
            "start": keep_segment.get("start"),
            "end": keep_segment.get("end"),
            "text": keep_segment.get("text"),
        },
        "segments": [_local_segment_payload(seg) for seg in candidate_segments],
    }
    prompt = f"{prompt_template_path.read_text(encoding='utf-8')}\n\n输入:\n{json.dumps(payload, ensure_ascii=False)}"
    result = provider.semantic_dedup(prompt)
    seg_by_id = {seg.id: seg for seg in candidate_segments}

    edits: list[EditDecision] = []
    reviews: list[dict] = []
    total_deleted = 0.0
    delete_ranges = result.get("delete_ranges", [])
    range_count_by_segment: dict[str, int] = {}
    for item in delete_ranges:
        if isinstance(item, dict):
            seg_id = str(item.get("segment_id", ""))
            range_count_by_segment[seg_id] = range_count_by_segment.get(seg_id, 0) + 1
    for item in delete_ranges:
        seg_id = str(item.get("segment_id", ""))
        seg = seg_by_id.get(seg_id)
        if not seg:
            reviews.append(_range_review(item, "local_refine_unknown_segment"))
            continue
        if not allow_multiple_ranges_per_segment and range_count_by_segment.get(seg_id, 0) > 1:
            reviews.append(_range_review(item, "local_refine_multiple_ranges_same_segment"))
            continue
        start = _to_float(item.get("start"))
        end = _to_float(item.get("end"))
        item_confidence = _to_float(item.get("confidence"))
        item_reason = str(item.get("reason") or reason)
        if end <= start:
            reviews.append(_range_review(item, "local_refine_invalid_range"))
            continue
        if end - start > max_delete_duration:
            reviews.append(_range_review(item, "local_refine_delete_too_long"))
            continue
        if item_confidence < min_confidence:
            reviews.append(_range_review(item, "local_refine_low_confidence"))
            continue
        if not _range_on_provider_boundary(seg, start, end):
            reviews.append(_range_review(item, "local_refine_range_not_on_provider_boundary"))
            continue
        if _would_leave_short_fragment(seg, start, end, min_remaining_fragment_chars):
            reviews.append(_range_review(item, "local_refine_would_leave_short_fragment"))
            continue
        guarded_start, guarded_end = _apply_local_boundary_guard(seg, start, end, boundary_guard)
        if guarded_end <= guarded_start:
            reviews.append(_range_review(item, "local_refine_delete_too_short_after_guard"))
            continue
        guarded_duration = guarded_end - guarded_start
        if total_deleted + guarded_duration > max_total_delete_duration:
            reviews.append(_range_review(item, "local_refine_total_delete_too_long"))
            continue
        total_deleted += guarded_duration
        edits.append(
            EditDecision(
                type="delete",
                start=round(guarded_start, 3),
                end=round(guarded_end, 3),
                reason=f"{item_reason}; local_refine semantic_dedup",
                source="semantic_dedup",
                confidence=item_confidence,
            )
        )

    reviews.extend(_normalize_review_needed(result.get("review_needed", [])))
    return edits, reviews


def _segment_has_provider_words(seg: TranscriptSegment) -> bool:
    return bool(seg.words) and all(word.timestamp_source == "provider" for word in seg.words)


def _local_segment_payload(seg: TranscriptSegment) -> dict:
    return {
        "segment_id": seg.id,
        "start": seg.start,
        "end": seg.end,
        "text": seg.text,
        "words": [
            {
                "word": word.word,
                "start": word.start,
                "end": word.end,
                "timestamp_source": word.timestamp_source,
            }
            for word in seg.words
        ],
    }


def _range_on_provider_boundary(seg: TranscriptSegment, start: float, end: float) -> bool:
    starts = {round(word.start, 3) for word in seg.words}
    ends = {round(word.end, 3) for word in seg.words}
    return round(start, 3) in starts and round(end, 3) in ends


def _apply_local_boundary_guard(seg: TranscriptSegment, start: float, end: float, guard: float) -> tuple[float, float]:
    if start <= seg.start + 0.02 and end >= seg.end - 0.02:
        return start, end
    duration = end - start
    max_guard = max(0.0, (duration - 0.20) / 2)
    actual_guard = min(max(0.0, guard), max_guard)
    return start + actual_guard, end - actual_guard


def _would_leave_short_fragment(
    seg: TranscriptSegment,
    start: float,
    end: float,
    min_remaining_fragment_chars: int,
) -> bool:
    if min_remaining_fragment_chars <= 0 or not seg.words:
        return False
    kept_chunks: list[str] = []
    current = []
    for word in seg.words:
        if max(start, word.start) < min(end, word.end):
            if current:
                kept_chunks.append("".join(current))
                current = []
            continue
        current.append(word.word)
    if current:
        kept_chunks.append("".join(current))
    if len(kept_chunks) == 1:
        delete_touches_edge = start <= seg.words[0].start + 0.02 or end >= seg.words[-1].end - 0.02
        return (not delete_touches_edge) and len(kept_chunks[0].strip()) < min_remaining_fragment_chars
    if len(kept_chunks) < 1:
        return False
    return any(len(chunk.strip()) < min_remaining_fragment_chars for chunk in kept_chunks)


def _local_review(semantic_segment: dict, item_type: str, reason: str, confidence: float) -> dict:
    return {
        "type": item_type,
        "segment_id": semantic_segment.get("segment_id", ""),
        "segment_text_preview": str(semantic_segment.get("text", ""))[:80],
        "confidence": confidence,
        "reason": reason,
    }


def _range_review(item: dict, item_type: str) -> dict:
    out = dict(item)
    out["type"] = item_type
    return out


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _build_prompt(template: str, window: list[dict]) -> str:
    payload = {"segments": window}
    return f"{template}\n\n输入:\n{json.dumps(payload, ensure_ascii=False)}"


def _trim_segment_text(segment: dict, max_chars: int) -> dict:
    trimmed = dict(segment)
    text = str(trimmed.get("text", ""))
    if len(text) > max_chars:
        trimmed["text"] = text[:max_chars]
    return trimmed


def _normalize_review_needed(items: list, seg_by_id: dict | None = None) -> list[dict]:
    """将 provider 返回的 review_needed 数据规范化为 list[dict]。"""
    normalized: list[dict] = []
    seg_by_id = seg_by_id or {}
    for item in items or []:
        if isinstance(item, dict):
            # 补充文本预览信息
            seg_id = item.get("segment_id", "")
            if seg_id and "segment_text_preview" not in item:
                seg = seg_by_id.get(seg_id, {})
                item["segment_text_preview"] = str(seg.get("text", ""))[:80]
            normalized.append(item)
            continue
        # 纯字符串类型的 review item，尝试提取 segment_id
        item_str = str(item)
        seg_id = item_str if item_str.startswith("s_") else ""
        preview = ""
        if seg_id:
            seg = seg_by_id.get(seg_id, {})
            preview = str(seg.get("text", ""))[:80]
        normalized.append(
            {
                "type": "provider_review_item",
                "detail": item_str,
                "segment_id": seg_id,
                "segment_text_preview": preview,
            }
        )
    return normalized
