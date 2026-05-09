"""停顿检测逻辑测试。"""

import pytest

from schemas.models import Transcript, TranscriptSegment, TranscriptWord
from scripts.detect_pauses import detect_pauses
from scripts.detect_pauses import detect_post_delete_pauses
from schemas.models import EditDecision


class TestPauseDetector:
    def test_generates_compress_pause_edit(self):
        t = Transcript(
            language="zh",
            segments=[
                TranscriptSegment(id="a", start=0.0, end=1.0, text="你好。", words=[]),
                TranscriptSegment(id="b", start=2.2, end=3.0, text="继续", words=[]),
            ],
        )
        edits = detect_pauses(t, pause_threshold=0.8, target_pause_duration=0.3, word_padding=0.05)
        assert len(edits) == 1
        assert edits[0].type == "compress_pause"
        assert edits[0].source == "pause_detector"
        assert edits[0].reason

    def test_detects_word_gap_inside_segment(self):
        t = Transcript(
            language="zh",
            segments=[
                TranscriptSegment(
                    id="a",
                    start=0.0,
                    end=3.0,
                    text="你好继续",
                    words=[
                        TranscriptWord(word="你好", start=0.0, end=0.4),
                        TranscriptWord(word="继续", start=1.4, end=2.0),
                    ],
                ),
            ],
        )
        edits = detect_pauses(t, pause_threshold=0.8, target_pause_duration=0.2, word_padding=0.05)
        assert len(edits) == 1
        assert edits[0].start == pytest.approx(0.45)
        assert edits[0].end == pytest.approx(1.35)

    def test_trims_leading_and_trailing_silence(self):
        t = Transcript(
            language="zh",
            segments=[
                TranscriptSegment(id="a", start=5.0, end=7.0, text="姝ｆ枃", words=[]),
            ],
        )
        edits = detect_pauses(
            t,
            pause_threshold=0.8,
            target_pause_duration=0.2,
            word_padding=0.05,
            trim_edge_silence=True,
            media_duration=10.0,
        )
        assert len(edits) == 2
        assert edits[0].start == 0.0
        assert edits[0].end == 5.0
        assert edits[1].start == 7.0
        assert edits[1].end == 10.0

    def test_detects_pause_exposed_after_delete(self):
        t = Transcript(
            language="zh",
            segments=[
                TranscriptSegment(id="seg-001", start=0.0, end=1.0, text="a", words=[]),
                TranscriptSegment(id="seg-002", start=1.2, end=2.0, text="duplicate", words=[]),
                TranscriptSegment(id="seg-003", start=4.0, end=5.0, text="b", words=[]),
            ],
        )
        edits = detect_post_delete_pauses(
            t,
            [
                EditDecision(
                    type="delete",
                    start=1.2,
                    end=2.0,
                    reason="local_refine",
                    source="semantic_dedup",
                    confidence=0.95,
                )
            ],
            pause_threshold=0.22,
            target_pause_duration=0.04,
            word_padding=0.01,
        )

        assert len(edits) == 1
        assert edits[0].type == "compress_pause"
        assert edits[0].start == pytest.approx(1.01)
        assert edits[0].end == pytest.approx(3.99)

    def test_post_delete_pause_uses_word_chunks_inside_segment(self):
        t = Transcript(
            language="zh",
            segments=[
                TranscriptSegment(
                    id="seg-001",
                    start=0.0,
                    end=5.0,
                    text="abcdef",
                    words=[
                        TranscriptWord(word="a", start=0.0, end=0.5, timestamp_source="provider"),
                        TranscriptWord(word="b", start=0.5, end=1.0, timestamp_source="provider"),
                        TranscriptWord(word="c", start=2.0, end=2.5, timestamp_source="provider"),
                        TranscriptWord(word="d", start=2.5, end=3.0, timestamp_source="provider"),
                        TranscriptWord(word="e", start=4.0, end=4.5, timestamp_source="provider"),
                    ],
                ),
            ],
        )
        edits = detect_post_delete_pauses(
            t,
            [
                EditDecision(
                    type="delete",
                    start=0.5,
                    end=1.0,
                    reason="delete b",
                    source="semantic_dedup",
                    confidence=0.95,
                )
            ],
            pause_threshold=0.22,
            target_pause_duration=0.04,
            word_padding=0.01,
        )

        assert all(edit.end <= 4.0 for edit in edits)
        assert any(edit.start == pytest.approx(0.51) and edit.end == pytest.approx(1.99) for edit in edits)
        assert not any(edit.start == pytest.approx(3.01) and edit.end == pytest.approx(3.99) for edit in edits)
