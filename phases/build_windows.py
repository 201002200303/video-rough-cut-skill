"""Phase 5: 五段窗口构建 — 把 flagged segment 扩展成带上下文的编辑窗口。"""

from __future__ import annotations

import json
from pathlib import Path

from core.utils import load_config, setup_logger
from schemas.models import SegmentIssue, SourceSegment, Window, WindowFile

logger = setup_logger(__name__)


def build_windows(
    source_segments: list[SourceSegment],
    flagged_issues: list[SegmentIssue],
    output_path: Path | None = None,
) -> WindowFile:
    """为每个 flagged segment 构造 5-segment 编辑窗口。

    - target: flagged segment(s)
    - left_context: 最多 N 个前导 segment（只读）
    - right_context: 最多 N 个后置 segment（只读）

    相邻 flagged segment 会合并到同一个窗口中。
    """
    cfg = load_config().get("window", {})
    left_n = int(cfg.get("left_context_segments", 2))
    right_n = int(cfg.get("right_context_segments", 2))
    merge_adjacent = bool(cfg.get("merge_adjacent_flagged", True))

    flagged_ids = {i.segment_id for i in flagged_issues}
    seg_index = {s.segment_id: idx for idx, s in enumerate(source_segments)}

    if not flagged_ids:
        logger.info("No flagged segments, no windows built")
        out = WindowFile()
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(out.model_dump_json(indent=2), encoding="utf-8")
        return out

    # 按顺序排列 flagged segments
    ordered_flagged = sorted(flagged_ids, key=lambda sid: seg_index.get(sid, 0))

    # 合并相邻 flagged
    groups: list[list[str]] = []
    for sid in ordered_flagged:
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

    windows: list[Window] = []
    for gi, group in enumerate(groups):
        first_idx = min(seg_index[s] for s in group)
        last_idx = max(seg_index[s] for s in group)

        left_start = max(0, first_idx - left_n)
        right_end = min(len(source_segments), last_idx + right_n + 1)

        target_ids = [source_segments[i].segment_id for i in range(first_idx, last_idx + 1)]
        left_ids = [source_segments[i].segment_id for i in range(left_start, first_idx)]
        right_ids = [source_segments[i].segment_id for i in range(last_idx + 1, right_end)]

        window = Window(
            window_id=f"win-{gi:03d}",
            target_segment_ids=target_ids,
            left_context_segment_ids=left_ids,
            right_context_segment_ids=right_ids,
            allowed_edit_segment_ids=list(target_ids),
        )
        windows.append(window)

    logger.info("Built %d windows from %d flagged segments (%d groups)", len(windows), len(flagged_ids), len(groups))

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
