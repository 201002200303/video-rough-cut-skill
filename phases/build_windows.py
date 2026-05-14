"""Phase 5: 五段窗口构建 — 把 flagged segment 扩展成带上下文的编辑窗口。"""

from __future__ import annotations

import json
from pathlib import Path

from core.utils import load_config, setup_logger
from schemas.models import SegmentIssue, SourceSegment, SourceWord, Window, WindowFile

logger = setup_logger(__name__)


def build_windows(
    source_segments: list[SourceSegment],
    flagged_issues: list[SegmentIssue],
    output_path: Path | None = None,
) -> WindowFile:
    """为每个 flagged segment 构造 5-segment 编辑窗口，按 phase 分拆。

    - target: flagged segment(s)
    - left_context: 最多 N 个前导 segment（只读）
    - right_context: 最多 N 个后置 segment（只读）
    - phase: 按 issue_types 自动分拆为 "correction" 或 "dedup"

    相邻同 phase 的 flagged segment 合并到同一个窗口。
    一个 segment 同时有纠错和去重 issue 时，两个窗口都会出现。
    """
    cfg = load_config().get("window", {})
    left_n = int(cfg.get("left_context_segments", 2))
    right_n = int(cfg.get("right_context_segments", 2))
    merge_adjacent = bool(cfg.get("merge_adjacent_flagged", True))

    seg_index = {s.segment_id: idx for idx, s in enumerate(source_segments)}

    # issue_types → phase 映射
    CORRECTION_TYPES = {"asr_homophone_error", "speaker_name_error", "missing_char", "extra_noise_char", "uncertain"}
    DEDUP_TYPES = {"false_start", "fast_repetition", "redundant_restatement", "incomplete_fragment", "filler_phrase"}

    # 按 phase 分组 flagged segment_ids
    correction_ids: set[str] = set()
    dedup_ids: set[str] = set()

    for issue in flagged_issues:
        types = set(issue.issue_types)
        in_correction = bool(types & CORRECTION_TYPES)
        in_dedup = bool(types & DEDUP_TYPES)
        # 如果 issue_types 为空或不在任何已知集合中，默认进纠错
        if not in_correction and not in_dedup:
            in_correction = True
        if in_correction:
            correction_ids.add(issue.segment_id)
        if in_dedup:
            dedup_ids.add(issue.segment_id)

    def _build_phase_windows(flagged_ids: set[str], phase: str) -> list[Window]:
        if not flagged_ids:
            return []
        ordered = sorted(flagged_ids, key=lambda sid: seg_index.get(sid, 0))
        groups: list[list[str]] = []
        for sid in ordered:
            if not groups:
                groups.append([sid])
            elif merge_adjacent:
                last_idx = seg_index.get(groups[-1][-1], -1)
                cur_idx = seg_index.get(sid, -1)
                if cur_idx - last_idx <= 1:
                    groups[-1].append(sid)
                else:
                    groups.append([sid])
            else:
                groups.append([sid])

        result: list[Window] = []
        for group in groups:
            first_idx = min(seg_index[s] for s in group)
            last_idx = max(seg_index[s] for s in group)
            left_start = max(0, first_idx - left_n)
            right_end = min(len(source_segments), last_idx + right_n + 1)
            target_ids = [source_segments[i].segment_id for i in range(first_idx, last_idx + 1)]
            left_ids = [source_segments[i].segment_id for i in range(left_start, first_idx)]
            right_ids = [source_segments[i].segment_id for i in range(last_idx + 1, right_end)]
            result.append(Window(
                window_id=f"win-{phase}-{len(result):03d}",
                phase=phase,
                target_segment_ids=target_ids,
                left_context_segment_ids=left_ids,
                right_context_segment_ids=right_ids,
                allowed_edit_segment_ids=list(target_ids),
            ))
        return result

    correction_windows = _build_phase_windows(correction_ids, "correction")
    dedup_windows = _build_phase_windows(dedup_ids, "dedup")
    windows = correction_windows + dedup_windows

    c_count = len(correction_windows)
    d_count = len(dedup_windows)
    logger.info("Built %d windows (%d correction + %d dedup) from %d flagged segments (%d correction + %d dedup)",
                len(windows), c_count, d_count, len(flagged_issues), len(correction_ids), len(dedup_ids))

    out = WindowFile(windows=windows)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(out.model_dump_json(indent=2), encoding="utf-8")

    return out


def get_window_segments(
    window: Window,
    source_segments: list[SourceSegment],
) -> list[SourceSegment]:
    """获取 window 中所有 segment 的有序列表。"""
    seg_by_id = {s.segment_id: s for s in source_segments}
    result: list[SourceSegment] = []
    for sid in window.all_segment_ids:
        if sid in seg_by_id:
            result.append(seg_by_id[sid])
    return result


def get_window_words(
    window: Window,
    source_words: list[SourceWord],
) -> list[SourceWord]:
    """获取 window 内所有 segment 的 source words。"""
    seg_ids = set(window.all_segment_ids)
    return [w for w in source_words if w.segment_id in seg_ids]
