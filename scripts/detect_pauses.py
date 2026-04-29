"""从转写数据中检测停顿，生成 compress_pause 编辑决策。"""

from pathlib import Path

from core.logging import setup_logger
from schemas.edit_decision import EditDecision
from schemas.transcript import Transcript

logger = setup_logger(__name__)


def detect_pauses(
    transcript: Transcript,
    pause_threshold: float = 0.8,
    target_pause_duration: float = 0.25,
    word_padding: float = 0.03,
    keep_sentence_boundary_pause: bool = True,
    sentence_boundary_pause_bonus: float = 0.3,
    use_word_gaps: bool = True,
) -> list[EditDecision]:
    """从可靠的相邻片段/字间间隔生成 compress_pause 编辑决策。"""
    edits: list[EditDecision] = []
    segs = transcript.segments
    for i in range(len(segs) - 1):
        left = segs[i]
        right = segs[i + 1]
        gap = right.start - left.end
        if gap < pause_threshold:
            continue
        threshold = pause_threshold
        if keep_sentence_boundary_pause and left.text.strip().endswith(("。", "？", "！", ".", "?", "!")):
            threshold = pause_threshold + sentence_boundary_pause_bonus
        if gap < threshold:
            continue
        _append_pause_edit(
            edits,
            left.end,
            right.start,
            word_padding,
            target_pause_duration,
            f"segment pause {gap:.2f}s >= threshold {threshold:.2f}s",
        )

    if use_word_gaps:
        words = sorted(
            [w for seg in segs for w in seg.words],
            key=lambda w: (w.start, w.end),
        )
        # 检测 word 时间戳是否为估算值（均匀分配），若是则跳过 word gap 检测。
        # 判断依据：相邻 word 间隔是否高度一致（标准差 < 均值的 15%）。
        if words and len(words) >= 3:
            gaps = [words[i + 1].start - words[i].end for i in range(len(words) - 1)]
            mean_gap = sum(gaps) / len(gaps)
            if mean_gap > 0:
                variance = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
                std_dev = variance ** 0.5
                if std_dev / mean_gap < 0.15:
                    logger.info("Word timestamps appear estimated (uniform gaps), skipping word gap detection")
                    use_word_gaps = False

        if use_word_gaps:
            for left, right in zip(words, words[1:]):
                gap = right.start - left.end
                if gap < pause_threshold:
                    continue
                _append_pause_edit(
                    edits,
                    left.end,
                    right.start,
                    word_padding,
                    target_pause_duration,
                    f"word pause {gap:.2f}s >= threshold {pause_threshold:.2f}s",
                )
    edits = _merge_overlapping_pause_edits(edits)
    logger.info("Pause detector generated %d edits", len(edits))
    return edits


def _append_pause_edit(
    edits: list[EditDecision],
    pause_start: float,
    pause_end: float,
    word_padding: float,
    target_pause_duration: float,
    reason: str,
) -> None:
    start = pause_start + word_padding
    end = pause_end - word_padding
    if end <= start:
        return
    edits.append(
        EditDecision(
            type="compress_pause",
            start=start,
            end=end,
            target_duration=target_pause_duration,
            source="pause_detector",
            reason=reason,
        )
    )


def _merge_overlapping_pause_edits(edits: list[EditDecision]) -> list[EditDecision]:
    if not edits:
        return []
    ordered = sorted(edits, key=lambda e: e.start)
    merged = [ordered[0]]
    for cur in ordered[1:]:
        last = merged[-1]
        if cur.start <= last.end:
            merged[-1] = EditDecision(
                type="compress_pause",
                start=last.start,
                end=max(last.end, cur.end),
                target_duration=min(
                    last.target_duration or 0.0,
                    cur.target_duration or 0.0,
                ),
                source="pause_detector",
                reason=f"{last.reason}; {cur.reason}",
            )
        else:
            merged.append(cur)
    return merged