"""停顿检测逻辑测试。"""

import pytest

from schemas.transcript import Transcript, TranscriptSegment, TranscriptWord
from scripts.detect_pauses import detect_pauses


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