"""Word-level repair pass for failed whole-unit false-start deletions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from core.utils import load_config, setup_logger
from providers.aliyun_qwen import AliyunQwenProvider
from schemas.models import EditDecision, TranscriptWord, UtteranceUnit

logger = setup_logger(__name__)


@dataclass(frozen=True)
class _WordRef:
    word_id: str
    unit_id: str
    word: TranscriptWord


def detect_local_false_start_repairs(
    units: list[UtteranceUnit],
    review_needed: list[dict],
    refine_prompt_template_path: Path,
    continuity_prompt_template_path: Path,
) -> tuple[list[EditDecision], list[dict]]:
    """Turn failed whole-unit false-start reviews into safe word-boundary deletes."""
    cfg = load_config().get("local_false_start_refine", {})
    if not bool(cfg.get("enabled", False)):
        return [], review_needed

    min_confidence = float(cfg.get("min_confidence", 0.92))
    continuity_min_confidence = float(cfg.get("continuity_min_confidence", 0.90))
    max_delete_duration = float(cfg.get("max_delete_duration", 4.0))
    max_window_units_before = int(cfg.get("max_window_units_before", 1))
    max_window_units_after = int(cfg.get("max_window_units_after", 2))
    min_remaining_chars = int(cfg.get("min_remaining_chars", 6))
    allow_multiple_ranges = bool(cfg.get("allow_multiple_ranges", False))

    if not refine_prompt_template_path.exists():
        return [], [*review_needed, {"type": "local_false_start_refine_prompt_missing"}]

    provider = AliyunQwenProvider()
    units_by_id = {unit.unit_id: unit for unit in units}
    edits: list[EditDecision] = []
    updated_reviews: list[dict] = []
    repaired_unit_ids: set[str] = set()

    for review in review_needed:
        unit_id = str(review.get("unit_id", ""))
        unit = units_by_id.get(unit_id)
        if unit_id in repaired_unit_ids:
            continue
        if not unit or not _should_refine(review):
            updated_reviews.append(review)
            continue

        window = _unit_window(units, unit, max_window_units_before, max_window_units_after)
        if not _window_has_provider_words(window):
            updated_reviews.append({**review, "local_refine_skip": "requires_provider_word_timestamps"})
            continue

        word_refs = _word_refs(window)
        try:
            result = provider.semantic_dedup(
                f"{refine_prompt_template_path.read_text(encoding='utf-8')}\n\n输入:\n"
                f"{json.dumps(_payload(review, window, word_refs), ensure_ascii=False)}"
            )
        except Exception as exc:
            updated_reviews.append({**review, "local_refine_error": str(exc)})
            continue

        range_items = [item for item in result.get("delete_word_ranges", []) if isinstance(item, dict)]
        if not allow_multiple_ranges and len(range_items) > 1:
            updated_reviews.append({**review, "local_refine_skip": "multiple_ranges"})
            continue

        candidate_edits: list[EditDecision] = []
        candidate_reviews: list[dict] = []
        for item in range_items:
            edit, item_review = _candidate_edit(
                item,
                review,
                window,
                word_refs,
                min_confidence,
                max_delete_duration,
                min_remaining_chars,
            )
            if item_review:
                candidate_reviews.append(item_review)
            if edit:
                continuity = _review_continuity(
                    provider,
                    window,
                    word_refs,
                    edit.start,
                    edit.end,
                    continuity_prompt_template_path,
                    item.get("reason") or review.get("candidate_reason", ""),
                )
                if bool(continuity.get("pass", False)) and _to_float(continuity.get("confidence")) >= continuity_min_confidence:
                    candidate_edits.append(
                        EditDecision(
                            type="delete",
                            start=edit.start,
                            end=edit.end,
                            reason=f"{edit.reason}; continuity_pass={continuity.get('reason', '')}",
                            source="local_false_start_refine",
                            confidence=edit.confidence,
                        )
                    )
                else:
                    candidate_reviews.append(
                        {
                            "type": "local_false_start_continuity_failed",
                            "unit_id": unit_id,
                            "start": edit.start,
                            "end": edit.end,
                            "continuity": continuity,
                        }
                    )

        if candidate_edits:
            edits.extend(candidate_edits)
            repaired_unit_ids.add(unit_id)
            logger.info("Local false-start repair generated %d edit(s) for %s", len(candidate_edits), unit_id)
        else:
            updated_reviews.append({**review, "local_refine_reviews": candidate_reviews or result.get("review_needed", [])})

    return edits, updated_reviews


def _should_refine(review: dict) -> bool:
    if review.get("type") != "unit_delete_continuity_failed":
        return False
    text = " ".join(
        str(review.get(key, ""))
        for key in ("text", "analysis_text", "candidate_reason")
    )
    continuity = review.get("continuity") or {}
    text += " " + str(continuity.get("reason", ""))
    keywords = ("口误", "改口", "重复", "重述", "残句", "不完整", "错词", "误读", "false start")
    return any(keyword in text for keyword in keywords)


def _unit_window(
    units: list[UtteranceUnit],
    unit: UtteranceUnit,
    before_count: int,
    after_count: int,
) -> list[UtteranceUnit]:
    index = next(i for i, item in enumerate(units) if item.unit_id == unit.unit_id)
    start = max(0, index - before_count)
    end = min(len(units), index + after_count + 1)
    return units[start:end]


def _window_has_provider_words(units: list[UtteranceUnit]) -> bool:
    return all(unit.words and unit.timestamp_source == "provider" for unit in units)


def _word_refs(units: list[UtteranceUnit]) -> list[_WordRef]:
    refs: list[_WordRef] = []
    for unit in units:
        for word in unit.words:
            refs.append(_WordRef(word_id=f"w-{len(refs) + 1:04d}", unit_id=unit.unit_id, word=word))
    return refs


def _payload(review: dict, units: list[UtteranceUnit], word_refs: list[_WordRef]) -> dict:
    return {
        "failed_review": review,
        "units": [
            {
                "unit_id": unit.unit_id,
                "start": unit.start,
                "end": unit.end,
                "text": unit.text,
                "analysis_text": unit.analysis_text or unit.text,
            }
            for unit in units
        ],
        "words": [
            {
                "word_id": ref.word_id,
                "unit_id": ref.unit_id,
                "word": ref.word.word,
                "start": ref.word.start,
                "end": ref.word.end,
            }
            for ref in word_refs
        ],
    }


def _candidate_edit(
    item: dict,
    review: dict,
    units: list[UtteranceUnit],
    word_refs: list[_WordRef],
    min_confidence: float,
    max_delete_duration: float,
    min_remaining_chars: int,
) -> tuple[EditDecision | None, dict | None]:
    by_id = {ref.word_id: index for index, ref in enumerate(word_refs)}
    start_id = str(item.get("start_word_id", ""))
    end_id = str(item.get("end_word_id", ""))
    if start_id not in by_id or end_id not in by_id:
        return None, {"type": "local_false_start_unknown_word_id", **item}
    start_index = by_id[start_id]
    end_index = by_id[end_id]
    if end_index < start_index:
        return None, {"type": "local_false_start_invalid_word_range", **item}
    start = word_refs[start_index].word.start
    end = word_refs[end_index].word.end
    confidence = _to_float(item.get("confidence"))
    if confidence < min_confidence:
        return None, {"type": "local_false_start_low_confidence", **item}
    if end - start > max_delete_duration:
        return None, {"type": "local_false_start_delete_too_long", **item}
    remaining_text = _remaining_text(word_refs, start_index, end_index)
    if len(remaining_text.strip()) < min_remaining_chars:
        return None, {"type": "local_false_start_remaining_too_short", **item, "remaining_text": remaining_text}
    reason = str(item.get("reason") or review.get("candidate_reason") or "local false-start repair")
    return (
        EditDecision(
            type="delete",
            start=round(start, 3),
            end=round(end, 3),
            reason=f"{reason}; local_false_start_refine",
            source="local_false_start_refine",
            confidence=confidence,
        ),
        None,
    )


def _remaining_text(word_refs: list[_WordRef], start_index: int, end_index: int) -> str:
    return "".join(
        ref.word.word
        for index, ref in enumerate(word_refs)
        if index < start_index or index > end_index
    )


def _review_continuity(
    provider: AliyunQwenProvider,
    units: list[UtteranceUnit],
    word_refs: list[_WordRef],
    delete_start: float,
    delete_end: float,
    prompt_template_path: Path,
    reason: str,
) -> dict:
    before_delete = " ".join(unit.analysis_text or unit.text for unit in units)
    after_delete = "".join(
        ref.word.word
        for ref in word_refs
        if not (max(ref.word.start, delete_start) < min(ref.word.end, delete_end))
    )
    payload = {
        "candidate": {
            "start": delete_start,
            "end": delete_end,
            "reason": reason,
        },
        "before_delete": before_delete,
        "after_delete": after_delete,
        "kept_unit_ids": [unit.unit_id for unit in units],
    }
    try:
        return provider.semantic_dedup(
            f"{prompt_template_path.read_text(encoding='utf-8')}\n\n输入:\n{json.dumps(payload, ensure_ascii=False)}"
        )
    except Exception as exc:
        return {"pass": False, "confidence": 0.0, "reason": f"continuity review failed: {exc}"}


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
