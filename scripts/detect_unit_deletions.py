"""LLM semantic deletion over numbered utterance units."""

from __future__ import annotations

import json
from pathlib import Path

from core.utils import load_config, setup_logger
from providers.aliyun_qwen import AliyunQwenProvider
from schemas.models import EditDecision, UtteranceUnit

logger = setup_logger(__name__)


def detect_unit_deletions(
    units: list[UtteranceUnit],
    analysis_prompt_template_path: Path,
    deletion_prompt_template_path: Path,
    continuity_prompt_template_path: Path,
) -> tuple[list[UtteranceUnit], list[EditDecision], list[dict]]:
    cfg = load_config().get("dedup", {})
    if not bool(cfg.get("enabled", True)):
        logger.info("Unit semantic deletion skipped: dedup.enabled=false")
        return units, [], []
    min_confidence = float(cfg.get("unit_delete_min_confidence", 0.90))
    continuity_min_confidence = float(cfg.get("continuity_review_min_confidence", 0.90))
    max_duration = float(cfg.get("max_auto_delete_unit_duration", 4.0))
    max_units_per_call = int(cfg.get("unit_llm_chunk_size", 24))

    provider = AliyunQwenProvider()
    corrected_units = _correct_analysis_text(provider, units, analysis_prompt_template_path, max_units_per_call)
    candidates, reviews = _detect_candidates(provider, corrected_units, deletion_prompt_template_path, max_units_per_call)
    edits: list[EditDecision] = []
    accepted_ids: set[str] = set()
    units_by_id = {unit.unit_id: unit for unit in corrected_units}

    for candidate in candidates:
        unit_id = str(candidate.get("unit_id", ""))
        unit = units_by_id.get(unit_id)
        confidence = _to_float(candidate.get("confidence"))
        reason = str(candidate.get("reason") or "unit semantic delete")
        if not unit:
            reviews.append({"type": "unit_delete_unknown_id", **candidate})
            continue
        if any(key in candidate for key in ("start", "end", "delete_ranges")):
            reviews.append({"type": "unit_delete_rejected_arbitrary_time_range", **candidate})
            continue
        if unit.timestamp_source != "provider" or not unit.words:
            reviews.append({"type": "unit_delete_requires_provider_timestamp", **candidate})
            continue
        if unit.end - unit.start > max_duration:
            reviews.append({"type": "unit_delete_too_long", **candidate, "duration": unit.end - unit.start})
            continue
        if confidence < min_confidence:
            reviews.append({"type": "unit_delete_low_confidence", **candidate})
            continue
        continuity = _review_continuity(
            provider,
            corrected_units,
            unit,
            accepted_ids,
            continuity_prompt_template_path,
        )
        if not bool(continuity.get("pass", False)) or _to_float(continuity.get("confidence")) < continuity_min_confidence:
            reviews.append(
                {
                    "type": "unit_delete_continuity_failed",
                    "unit_id": unit_id,
                    "text": unit.text,
                    "analysis_text": unit.analysis_text,
                    "candidate_reason": reason,
                    "continuity": continuity,
                }
            )
            continue
        accepted_ids.add(unit_id)
        edits.append(
            EditDecision(
                type="delete",
                start=unit.words[0].start,
                end=unit.words[-1].end,
                reason=f"{reason}; unit_delete; continuity_pass={continuity.get('reason', '')}",
                source="semantic_dedup",
                confidence=confidence,
            )
        )

    logger.info("Unit semantic deletion edits=%d review_needed=%d", len(edits), len(reviews))
    return corrected_units, edits, reviews


def _correct_analysis_text(
    provider: AliyunQwenProvider,
    units: list[UtteranceUnit],
    prompt_template_path: Path,
    chunk_size: int,
) -> list[UtteranceUnit]:
    prompt_template = prompt_template_path.read_text(encoding="utf-8")
    text_by_id: dict[str, str] = {}
    for chunk in _chunks(units, chunk_size):
        payload = {"units": [_unit_payload(unit) for unit in chunk]}
        try:
            result = provider.semantic_dedup(f"{prompt_template}\n\n输入:\n{json.dumps(payload, ensure_ascii=False)}")
        except Exception as exc:
            logger.warning("Analysis text correction failed for a chunk; using original text: %s", exc)
            continue
        for item in result.get("units", []):
            if isinstance(item, dict):
                unit_id = str(item.get("unit_id", ""))
                analysis_text = str(item.get("analysis_text", "")).strip()
                if unit_id and analysis_text:
                    text_by_id[unit_id] = analysis_text

    corrected = []
    for unit in units:
        corrected.append(
            UtteranceUnit(
                unit_id=unit.unit_id,
                start=unit.start,
                end=unit.end,
                text=unit.text,
                analysis_text=text_by_id.get(unit.unit_id, unit.analysis_text or unit.text),
                source_segment_ids=unit.source_segment_ids,
                words=unit.words,
                timestamp_source=unit.timestamp_source,
            )
        )
    return corrected


def _detect_candidates(
    provider: AliyunQwenProvider,
    units: list[UtteranceUnit],
    prompt_template_path: Path,
    chunk_size: int,
) -> tuple[list[dict], list[dict]]:
    prompt_template = prompt_template_path.read_text(encoding="utf-8")
    candidates: list[dict] = []
    reviews: list[dict] = []
    for chunk in _windowed_units(units, chunk_size):
        payload = {"units": [_unit_payload(unit) for unit in chunk]}
        try:
            result = provider.semantic_dedup(f"{prompt_template}\n\n输入:\n{json.dumps(payload, ensure_ascii=False)}")
        except Exception as exc:
            reviews.append({"type": "unit_delete_llm_failed", "error": str(exc), "unit_ids": [u.unit_id for u in chunk]})
            continue
        for item in result.get("delete_unit_ids", []):
            if isinstance(item, dict):
                candidates.append(item)
            else:
                candidates.append({"unit_id": str(item), "confidence": result.get("confidence", 0.0), "reason": result.get("reason", "unit semantic delete")})
        for item in result.get("delete_units", []):
            if isinstance(item, dict):
                candidates.append(item)
        for item in result.get("review_unit_ids", []):
            reviews.append({"type": "unit_delete_llm_review", "unit_id": item})
        for item in result.get("review_needed", []):
            reviews.append(item if isinstance(item, dict) else {"type": "unit_delete_llm_review", "detail": str(item)})
    return candidates, reviews


def _review_continuity(
    provider: AliyunQwenProvider,
    units: list[UtteranceUnit],
    candidate: UtteranceUnit,
    accepted_ids: set[str],
    prompt_template_path: Path,
) -> dict:
    kept = [unit for unit in units if unit.unit_id not in accepted_ids and unit.unit_id != candidate.unit_id]
    before = _neighbor(units, candidate, -1, accepted_ids)
    after = _neighbor(units, candidate, 1, accepted_ids)
    payload = {
        "candidate": _unit_payload(candidate),
        "before_delete": " ".join(
            text
            for text in [
                before.analysis_text if before else "",
                candidate.analysis_text,
                after.analysis_text if after else "",
            ]
            if text
        ),
        "after_delete": " ".join(
            text for text in [before.analysis_text if before else "", after.analysis_text if after else ""] if text
        ),
        "kept_unit_ids": [unit.unit_id for unit in kept],
    }
    try:
        return provider.semantic_dedup(
            f"{prompt_template_path.read_text(encoding='utf-8')}\n\n输入:\n{json.dumps(payload, ensure_ascii=False)}"
        )
    except Exception as exc:
        return {"pass": False, "confidence": 0.0, "reason": f"continuity review failed: {exc}"}


def _neighbor(units: list[UtteranceUnit], candidate: UtteranceUnit, direction: int, deleted_ids: set[str]) -> UtteranceUnit | None:
    idx = next((i for i, unit in enumerate(units) if unit.unit_id == candidate.unit_id), -1)
    if idx < 0:
        return None
    cur = idx + direction
    while 0 <= cur < len(units):
        if units[cur].unit_id not in deleted_ids:
            return units[cur]
        cur += direction
    return None


def _unit_payload(unit: UtteranceUnit) -> dict:
    return {
        "unit_id": unit.unit_id,
        "start": unit.start,
        "end": unit.end,
        "duration": round(unit.end - unit.start, 3),
        "text": unit.text,
        "analysis_text": unit.analysis_text or unit.text,
        "timestamp_source": unit.timestamp_source,
    }


def _chunks(items: list[UtteranceUnit], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _windowed_units(items: list[UtteranceUnit], size: int):
    if len(items) <= size:
        yield items
        return
    step = max(1, size // 2)
    seen_starts = set()
    for start in range(0, len(items), step):
        if start in seen_starts:
            continue
        seen_starts.add(start)
        chunk = items[start : start + size]
        if len(chunk) >= 2:
            yield chunk
        if start + size >= len(items):
            break


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
