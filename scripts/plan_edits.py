"""将停顿编辑和语义去重编辑合并为最终决策。"""

import json
from pathlib import Path

from core.utils import setup_logger
from schemas.models import EditDecision, EditDecisionFile

logger = setup_logger(__name__)


def plan_edits(
    pause_edits: list[EditDecision],
    semantic_edits: list[EditDecision],
    review_needed: list[dict],
    output_path: Path,
) -> EditDecisionFile:
    """按优先级和重叠规则合并编辑决策。"""
    merged_deletes = _merge_delete_edits([e for e in semantic_edits if e.type == "delete"])
    pause_only = []
    for pe in pause_edits:
        pause_only.extend(_subtract_deletes_from_pause(pe, merged_deletes))
    merged_pauses = _merge_pause_edits(pause_only)
    edits = sorted([*merged_deletes, *merged_pauses], key=lambda x: x.start)
    out = EditDecisionFile(edits=edits, review_needed=review_needed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Planned edits saved: %s (count=%d)", output_path, len(edits))
    return out


def _merge_delete_edits(deletes: list[EditDecision]) -> list[EditDecision]:
    if not deletes:
        return []
    ds = sorted(deletes, key=lambda x: x.start)
    merged = [ds[0]]
    for cur in ds[1:]:
        last = merged[-1]
        if cur.start <= last.end:
            merged[-1] = EditDecision(
                type="delete",
                start=last.start,
                end=max(last.end, cur.end),
                reason=f"{last.reason}; {cur.reason}",
                source="semantic_dedup",
                confidence=max(last.confidence or 0.0, cur.confidence or 0.0),
            )
        else:
            merged.append(cur)
    return merged


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    return max(a_start, b_start) < min(a_end, b_end)


def _subtract_deletes_from_pause(pause: EditDecision, deletes: list[EditDecision]) -> list[EditDecision]:
    ranges = [(pause.start, pause.end)]
    for delete in deletes:
        next_ranges = []
        for start, end in ranges:
            if not _overlap(start, end, delete.start, delete.end):
                next_ranges.append((start, end))
                continue
            if start < delete.start:
                next_ranges.append((start, min(end, delete.start)))
            if delete.end < end:
                next_ranges.append((max(start, delete.end), end))
        ranges = next_ranges
    out = []
    for start, end in ranges:
        if end <= start:
            continue
        out.append(
            EditDecision(
                type="compress_pause",
                start=start,
                end=end,
                reason=pause.reason,
                source=pause.source,
                target_duration=pause.target_duration,
                confidence=pause.confidence,
            )
        )
    return out


def _merge_pause_edits(pauses: list[EditDecision]) -> list[EditDecision]:
    if not pauses:
        return []
    ordered = sorted(pauses, key=lambda item: item.start)
    merged = [ordered[0]]
    for cur in ordered[1:]:
        last = merged[-1]
        if cur.start <= last.end:
            merged[-1] = EditDecision(
                type="compress_pause",
                start=last.start,
                end=max(last.end, cur.end),
                reason=f"{last.reason}; {cur.reason}",
                source="pause_detector",
                target_duration=min(last.target_duration or 0.0, cur.target_duration or 0.0),
                confidence=None,
            )
        else:
            merged.append(cur)
    return merged
