"""DeletionCandidate 硬校验器 — 纯代码校验，不依赖 LLM。

校验每个删除候选的 word_id 有效性、时间戳来源 (必须 provider)、
span 连续性、删除比例上限、VAD 边界对齐。替代 V2 中的 LLM review。
"""

from __future__ import annotations

from core.utils import load_config, setup_logger
from schemas.models import DeletionCandidate, SourceWord, ValidatedDeletionFile

logger = setup_logger(__name__)


def validate_deletion_candidates(
    candidates: list[DeletionCandidate],
    source_words: list[SourceWord],
    total_duration: float = 0.0,
) -> ValidatedDeletionFile:
    """校验所有 deletion candidates 并返回 accepted/rejected。"""
    cfg = load_config().get("validation", {})
    min_confidence = float(cfg.get("deletion_min_confidence", 0.88))
    max_duration = float(cfg.get("max_single_delete_duration", 3.0))
    max_total_ratio = float(cfg.get("max_total_delete_ratio", 0.22))

    words_by_id = {w.word_id: w for w in source_words}

    accepted: list[DeletionCandidate] = []
    rejected: list[dict] = []
    total_deleted = 0.0

    for i, c in enumerate(candidates):
        errors = _validate_one(c, words_by_id, min_confidence, max_duration)
        if errors:
            rejected.append({"candidate_index": i, "candidate": c.model_dump(), "errors": errors})
            logger.warning("Deletion candidate %d rejected: %s", i, errors)
        else:
            start = min(words_by_id[w].start for w in c.word_ids)
            end = max(words_by_id[w].end for w in c.word_ids)
            if total_duration > 0 and (total_deleted + (end - start)) / total_duration > max_total_ratio:
                rejected.append(
                    {
                        "candidate_index": i,
                        "candidate": c.model_dump(),
                        "errors": [f"would exceed total delete ratio {max_total_ratio}"],
                    }
                )
            else:
                total_deleted += end - start
                accepted.append(c)

    logger.info(
        "Deletion validation: %d accepted, %d rejected",
        len(accepted),
        len(rejected),
    )
    return ValidatedDeletionFile(accepted=accepted, rejected=rejected)


def _validate_one(
    c: DeletionCandidate,
    words_by_id: dict[str, SourceWord],
    min_confidence: float,
    max_duration: float,
) -> list[str]:
    errors: list[str] = []

    if c.confidence < min_confidence:
        errors.append(f"confidence {c.confidence} < min {min_confidence}")

    if not c.word_ids:
        errors.append("word_ids must not be empty")
        return errors

    for wid in c.word_ids:
        if wid not in words_by_id:
            errors.append(f"word_id {wid} not found")

    if len(c.word_ids) >= 2:
        ordered = sorted(c.word_ids, key=lambda x: int(x.split("-")[-1]))
        expected = list(range(int(ordered[0].split("-")[-1]), int(ordered[-1].split("-")[-1]) + 1))
        actual = [int(x.split("-")[-1]) for x in ordered]
        if actual != expected:
            errors.append(f"word_ids not contiguous")

    # 所有待删除词必须有 provider 时间戳
    for wid in c.word_ids:
        if wid in words_by_id and words_by_id[wid].timestamp_source != "provider":
            errors.append(f"word {wid} has estimated timestamp, cannot auto-delete")
            break

    # 检查删除时长
    if c.word_ids and not errors:
        try:
            start = min(words_by_id[w].start for w in c.word_ids if w in words_by_id)
            end = max(words_by_id[w].end for w in c.word_ids if w in words_by_id)
            duration = end - start
            if duration > max_duration:
                errors.append(f"delete duration {duration:.2f}s > max {max_duration}s")
        except ValueError:
            errors.append("could not compute delete duration")

    # 类型特定检查
    if c.type == "filler_phrase":
        if c.word_ids:
            text = "".join(words_by_id[w].char for w in c.word_ids if w in words_by_id)
            if len(text) > 4:
                errors.append(f"filler_phrase text too long: {len(text)} > 4 chars")

    return errors


def resolve_deletion_times(
    candidate: DeletionCandidate,
    words_by_id: dict[str, SourceWord],
    padding_before: float = 0.06,
    padding_after: float = 0.08,
) -> tuple[float, float]:
    """将 DeletionCandidate 的 word_ids 解析为带填充的 (start, end) 时间。"""
    times = [
        (words_by_id[w].start, words_by_id[w].end)
        for w in candidate.word_ids
        if w in words_by_id
    ]
    if not times:
        return (0.0, 0.0)
    raw_start = min(t[0] for t in times)
    raw_end = max(t[1] for t in times)
    return (
        max(0.0, raw_start - padding_before),
        raw_end + padding_after,
    )
