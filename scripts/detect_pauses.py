"""从转写数据中检测停顿，生成 compress_pause 编辑决策。"""

from pathlib import Path

from core.utils import setup_logger
from schemas.models import EditDecision
from schemas.models import Transcript
from schemas.models import TranscriptSegment

logger = setup_logger(__name__)


def detect_pauses(
    transcript: Transcript,
    pause_threshold: float = 0.8,
    target_pause_duration: float = 0.25,
    word_padding: float = 0.03,
    keep_sentence_boundary_pause: bool = True,
    sentence_boundary_pause_bonus: float = 0.3,
    use_word_gaps: bool = True,
    word_gap_threshold: float | None = None,
    trim_edge_silence: bool = True,
    media_duration: float | None = None,
) -> list[EditDecision]:
    """从可靠的相邻片段/字间间隔生成 compress_pause 编辑决策。"""
    edits: list[EditDecision] = []
    segs = transcript.segments
    if trim_edge_silence and segs:
        first = segs[0]
        if first.start >= pause_threshold:
            _append_pause_edit(
                edits,
                0.0,
                first.start,
                0.0,
                target_pause_duration,
                f"leading silence {first.start:.2f}s >= threshold {pause_threshold:.2f}s",
            )
        if media_duration is not None and media_duration > segs[-1].end:
            tail_gap = media_duration - segs[-1].end
            if tail_gap >= pause_threshold:
                _append_pause_edit(
                    edits,
                    segs[-1].end,
                    media_duration,
                    0.0,
                    target_pause_duration,
                    f"trailing silence {tail_gap:.2f}s >= threshold {pause_threshold:.2f}s",
                )
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
        word_gap_threshold = float(word_gap_threshold if word_gap_threshold is not None else pause_threshold)
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
                if gap < word_gap_threshold:
                    continue
                _append_pause_edit(
                    edits,
                    left.end,
                    right.start,
                    word_padding,
                    target_pause_duration,
                    f"word pause {gap:.2f}s >= threshold {word_gap_threshold:.2f}s",
                )
    edits = _merge_overlapping_pause_edits(edits)
    logger.info("Pause detector generated %d edits", len(edits))
    return edits


def detect_post_delete_pauses(
    transcript: Transcript,
    existing_edits: list[EditDecision],
    pause_threshold: float = 0.22,
    target_pause_duration: float = 0.04,
    word_padding: float = 0.01,
) -> list[EditDecision]:
    """Detect gaps exposed after semantic deletes and existing pause compression."""
    delete_edits = [edit for edit in existing_edits if edit.type == "delete"]
    kept_ranges = _kept_speech_ranges_after_deletes(transcript, delete_edits)

    edits: list[EditDecision] = []
    for left_start, left_end, right_start, right_end in zip(
        [item[0] for item in kept_ranges],
        [item[1] for item in kept_ranges],
        [item[0] for item in kept_ranges[1:]],
        [item[1] for item in kept_ranges[1:]],
    ):
        if not _delete_between(left_end, right_start, delete_edits):
            continue
        mapped_left_end = _map_time(left_end, existing_edits)
        mapped_right_start = _map_time(right_start, existing_edits)
        gap = mapped_right_start - mapped_left_end
        if gap < pause_threshold:
            continue
        _append_pause_edit(
            edits,
            left_end,
            right_start,
            word_padding,
            target_pause_duration,
            f"post-delete pause {gap:.2f}s >= threshold {pause_threshold:.2f}s",
        )
    if edits:
        logger.info("Post-delete pause detector generated %d edits", len(edits))
    return edits


def _kept_speech_ranges_after_deletes(
    transcript: Transcript,
    delete_edits: list[EditDecision],
) -> list[tuple[float, float]]:
    kept_ranges: list[tuple[float, float]] = []
    for seg in transcript.segments:
        if seg.words:
            for word in seg.words:
                if _overlaps_delete(word.start, word.end, delete_edits):
                    continue
                kept_ranges.append((word.start, word.end))
            continue
        if _inside_delete(seg.start, seg.end, delete_edits):
            continue
        start, end = _clamp_to_keep(seg.start, seg.end, delete_edits)
        if end > start:
            kept_ranges.append((start, end))
    return sorted(kept_ranges, key=lambda item: (item[0], item[1]))


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


def _map_time(t: float, edits: list[EditDecision]) -> float:
    shift = 0.0
    for edit in sorted(edits, key=lambda item: item.start):
        if edit.type == "delete":
            if t >= edit.end:
                shift += edit.end - edit.start
        elif edit.type == "compress_pause":
            if t >= edit.end:
                shift += (edit.end - edit.start) - (edit.target_duration or 0.0)
    return max(0.0, t - shift)


def _inside_delete(start: float, end: float, edits: list[EditDecision]) -> bool:
    return any(edit.type == "delete" and start >= edit.start and end <= edit.end for edit in edits)


def _overlaps_delete(start: float, end: float, edits: list[EditDecision]) -> bool:
    return any(edit.type == "delete" and max(start, edit.start) < min(end, edit.end) for edit in edits)


def _delete_between(start: float, end: float, edits: list[EditDecision]) -> bool:
    if end <= start:
        return False
    return any(edit.type == "delete" and max(start, edit.start) < min(end, edit.end) for edit in edits)


def _clamp_to_keep(start: float, end: float, edits: list[EditDecision]) -> tuple[float, float]:
    for edit in edits:
        if edit.type != "delete":
            continue
        if start < edit.start < end:
            end = edit.start
        if start < edit.end < end:
            start = edit.end
    return start, end
