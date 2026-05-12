"""五段窗口构建测试。"""

from schemas.models import SegmentIssue, SourceSegment, Window, WindowFile
from phases.build_windows import build_windows, get_window_segments


def _seg(seg_id, text, start=0.0, end=1.0):
    return SourceSegment(segment_id=seg_id, text=text, start=start, end=end, word_ids=[])


class TestBuildWindows:
    def test_no_flagged_segments_returns_empty(self):
        segments = [_seg("seg-001", "你好"), _seg("seg-002", "世界")]
        result = build_windows(segments, [])
        assert len(result.windows) == 0

    def test_single_flagged_creates_5_window(self):
        segments = [
            _seg("seg-001", "前前"),
            _seg("seg-002", "前"),
            _seg("seg-003", "目标"),
            _seg("seg-004", "后"),
            _seg("seg-005", "后后"),
        ]
        issues = [SegmentIssue(segment_id="seg-003", priority="high")]
        result = build_windows(segments, issues)
        assert len(result.windows) == 1
        w = result.windows[0]
        assert w.target_segment_ids == ["seg-003"]
        assert w.left_context_segment_ids == ["seg-001", "seg-002"]
        assert w.right_context_segment_ids == ["seg-004", "seg-005"]

    def test_adjacent_flagged_merge(self):
        segments = [
            _seg("seg-001", "前"),
            _seg("seg-002", "目标1"),
            _seg("seg-003", "目标2"),
            _seg("seg-004", "后"),
            _seg("seg-005", "后后"),
        ]
        issues = [
            SegmentIssue(segment_id="seg-002", priority="high"),
            SegmentIssue(segment_id="seg-003", priority="medium"),
        ]
        result = build_windows(segments, issues)
        assert len(result.windows) == 1
        w = result.windows[0]
        assert w.target_segment_ids == ["seg-002", "seg-003"]

    def test_separated_flagged_create_separate_windows(self):
        segments = [
            _seg("seg-001", "前"),
            _seg("seg-002", "目标1"),
            _seg("seg-003", "中间"),
            _seg("seg-004", "中间"),
            _seg("seg-005", "目标2"),
            _seg("seg-006", "后"),
        ]
        issues = [
            SegmentIssue(segment_id="seg-002", priority="high"),
            SegmentIssue(segment_id="seg-005", priority="high"),
        ]
        result = build_windows(segments, issues)
        assert len(result.windows) == 2

    def test_edge_window_at_start(self):
        segments = [
            _seg("seg-001", "目标"),
            _seg("seg-002", "后1"),
            _seg("seg-003", "后2"),
        ]
        issues = [SegmentIssue(segment_id="seg-001", priority="high")]
        result = build_windows(segments, issues)
        w = result.windows[0]
        assert w.left_context_segment_ids == []  # No left neighbors
        assert w.right_context_segment_ids == ["seg-002", "seg-003"]

    def test_edge_window_at_end(self):
        segments = [
            _seg("seg-001", "前1"),
            _seg("seg-002", "前2"),
            _seg("seg-003", "目标"),
        ]
        issues = [SegmentIssue(segment_id="seg-003", priority="high")]
        result = build_windows(segments, issues)
        w = result.windows[0]
        assert w.right_context_segment_ids == []  # No right neighbors

    def test_get_window_segments(self):
        segments = [
            _seg("seg-001", "a"),
            _seg("seg-002", "b", start=1.0, end=2.0),
            _seg("seg-003", "c", start=2.0, end=3.0),
        ]
        w = Window(
            window_id="win-000",
            target_segment_ids=["seg-002"],
            left_context_segment_ids=["seg-001"],
            right_context_segment_ids=["seg-003"],
            allowed_edit_segment_ids=["seg-002"],
        )
        ws = get_window_segments(w, segments)
        assert len(ws) == 3
        assert ws[0].segment_id == "seg-001"
        assert ws[1].segment_id == "seg-002"


class TestPriorityFiltering:
    def test_medium_priority_filtered_when_min_is_high(self):
        # 通过 _priority_meets 逻辑验证
        from phases.screen_segment_issues import _priority_meets

        assert _priority_meets("high", "high")
        assert _priority_meets("medium", "medium")
        assert not _priority_meets("low", "medium")
        assert not _priority_meets("low", "high")
        assert _priority_meets("medium", "low")
