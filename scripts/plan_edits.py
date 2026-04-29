"""将停顿编辑和语义去重编辑合并为最终决策。"""

import json
from pathlib import Path

from core.logging import setup_logger
from schemas.edit_decision import EditDecision, EditDecisionFile

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
        overlaps_delete = any(_overlap(pe.start, pe.end, de.start, de.end) for de in merged_deletes)
        if not overlaps_delete:
            pause_only.append(pe)
    edits = sorted([*merged_deletes, *pause_only], key=lambda x: x.start)
    out = EditDecisionFile(edits=edits, review_needed=review_needed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(out.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")
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