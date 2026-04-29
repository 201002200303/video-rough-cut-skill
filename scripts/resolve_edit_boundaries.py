"""用 timestamp_source 与 VAD 结果校验 LLM 剪辑边界。"""

from core.config import load_config
from core.logging import setup_logger
from schemas.edit_decision import EditDecision
from schemas.transcript import Transcript

logger = setup_logger(__name__)

LLM_DELETE_SOURCES = {"semantic_dedup", "content_cleanup"}


def resolve_edit_boundaries(
    edits: list[EditDecision],
    transcript: Transcript,
    vad_data: dict,
    review_needed: list[dict],
) -> tuple[list[EditDecision], list[dict]]:
    """将 LLM 删除候选转换为安全可执行编辑。

    目前的安全策略：
    - pause_detector 等规则型编辑直接放行。
    - LLM 删除若落在 estimated word timestamp 上，默认转 review。
    - 允许 content_cleanup 的高置信短删段在 estimated timestamp 下自动执行，用于当前无 FileTrans 权限时的实用粗剪。
    - 若存在 provider 级时间戳，则可选用 VAD 边界做轻微吸附。
    """
    cfg = load_config().get("boundary_resolver", {})
    require_provider = bool(cfg.get("require_provider_timestamps_for_llm_edits", True))
    align_to_vad = bool(cfg.get("align_to_vad", True))
    max_boundary_shift = float(cfg.get("max_boundary_shift", 0.35))
    allow_estimated_cleanup = bool(cfg.get("allow_estimated_content_cleanup_edits", False))
    estimated_cleanup_min_confidence = float(cfg.get("estimated_content_cleanup_min_confidence", 0.96))
    estimated_cleanup_max_duration = float(cfg.get("estimated_content_cleanup_max_duration", 2.5))

    safe_edits: list[EditDecision] = []
    reviews = list(review_needed)
    for edit in edits:
        if edit.type != "delete" or edit.source not in LLM_DELETE_SOURCES:
            safe_edits.append(edit)
            continue

        covered_words = _words_in_range(transcript, edit.start, edit.end)
        if require_provider and (not covered_words or any(w.timestamp_source != "provider" for w in covered_words)):
            if _can_accept_estimated_cleanup(
                edit,
                allow_estimated_cleanup,
                estimated_cleanup_min_confidence,
                estimated_cleanup_max_duration,
            ):
                safe_edits.append(
                    EditDecision(
                        type=edit.type,
                        start=edit.start,
                        end=edit.end,
                        reason=f"{edit.reason}; estimated timestamp 高置信短删段放行",
                        source=edit.source,
                        confidence=edit.confidence,
                        target_duration=edit.target_duration,
                    )
                )
                continue
            reviews.append(
                {
                    "type": "llm_delete_requires_provider_timestamp",
                    "start": edit.start,
                    "end": edit.end,
                    "source": edit.source,
                    "confidence": edit.confidence,
                    "reason": edit.reason,
                    "text_preview": "".join(w.word for w in covered_words)[:100],
                }
            )
            continue

        start, end = edit.start, edit.end
        if align_to_vad:
            start, end = _align_to_vad_silence(start, end, vad_data, max_boundary_shift)
        if end <= start:
            reviews.append(
                {
                    "type": "llm_delete_invalid_after_vad_alignment",
                    "start": edit.start,
                    "end": edit.end,
                    "source": edit.source,
                    "reason": edit.reason,
                }
            )
            continue
        safe_edits.append(
            EditDecision(
                type=edit.type,
                start=start,
                end=end,
                reason=f"{edit.reason}; boundary_resolver 已校验",
                source=edit.source,
                confidence=edit.confidence,
                target_duration=edit.target_duration,
            )
        )
    logger.info("Resolved edit boundaries: safe=%d review=%d", len(safe_edits), len(reviews))
    return safe_edits, reviews


def _can_accept_estimated_cleanup(
    edit: EditDecision,
    allow_estimated_cleanup: bool,
    min_confidence: float,
    max_duration: float,
) -> bool:
    """无 provider 时间戳时，仅放行 content_cleanup 的短、高置信删段。"""
    if not allow_estimated_cleanup or edit.source != "content_cleanup":
        return False
    if (edit.confidence or 0.0) < min_confidence:
        return False
    return 0 < edit.end - edit.start <= max_duration


def _words_in_range(transcript: Transcript, start: float, end: float):
    words = []
    for seg in transcript.segments:
        for word in seg.words:
            if max(start, word.start) < min(end, word.end):
                words.append(word)
    return words


def _align_to_vad_silence(start: float, end: float, vad_data: dict, max_shift: float) -> tuple[float, float]:
    """将边界吸附到附近静音段边缘；找不到就保留原值。"""
    silences = vad_data.get("silence_segments", []) if vad_data else []
    new_start = start
    new_end = end
    start_candidates = [float(s["start"]) for s in silences] + [float(s["end"]) for s in silences]
    end_candidates = list(start_candidates)
    near_start = _nearest(start, start_candidates, max_shift)
    near_end = _nearest(end, end_candidates, max_shift)
    if near_start is not None:
        new_start = near_start
    if near_end is not None:
        new_end = near_end
    return new_start, new_end


def _nearest(value: float, candidates: list[float], max_shift: float) -> float | None:
    if not candidates:
        return None
    best = min(candidates, key=lambda x: abs(x - value))
    return best if abs(best - value) <= max_shift else None
