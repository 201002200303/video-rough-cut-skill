"""时间线重映射逻辑测试。"""

from schemas.models import EditDecision, EditDecisionFile
from schemas.models import Transcript, TranscriptSegment, TranscriptWord
from scripts.remap_timeline import remap_timeline
import pytest


class TestTimelineRemap:
    def test_delete_and_shift(self, tmp_path):
        transcript = Transcript(
            language="zh",
            segments=[
                TranscriptSegment(id="s1", start=0.0, end=1.0, text="A", words=[]),
                TranscriptSegment(id="s2", start=1.5, end=2.0, text="B", words=[]),
                TranscriptSegment(id="s3", start=3.0, end=4.0, text="C", words=[]),
            ],
        )
        edits = EditDecisionFile(
            edits=[EditDecision(type="delete", start=1.4, end=2.2, reason="x", source="semantic_dedup")]
        )
        out = remap_timeline(transcript, edits, tmp_path / "remapped.json")
        assert len(out.segments) == 2
        assert out.segments[1].start < 3.0

    def test_partial_overlap_clamps_segment_tail(self, tmp_path):
        transcript = Transcript(
            language="zh",
            segments=[
                TranscriptSegment(id="s1", start=0.0, end=2.0, text="A", words=[]),
            ],
        )
        edits = EditDecisionFile(
            edits=[EditDecision(type="delete", start=1.5, end=2.5, reason="x", source="semantic_dedup")]
        )
        out = remap_timeline(transcript, edits, tmp_path / "remapped.json")
        assert len(out.segments) == 1
        assert out.segments[0].start == 0.0
        assert out.segments[0].end == 1.5

    def test_word_remap_drops_overlapped_words_and_splits_chunks(self, tmp_path):
        transcript = Transcript(
            language="zh",
            segments=[
                TranscriptSegment(
                    id="s1",
                    start=0.0,
                    end=3.0,
                    text="abcdef",
                    words=[
                        TranscriptWord(word="a", start=0.0, end=0.5, timestamp_source="provider"),
                        TranscriptWord(word="b", start=0.5, end=1.0, timestamp_source="provider"),
                        TranscriptWord(word="c", start=1.0, end=1.5, timestamp_source="provider"),
                        TranscriptWord(word="d", start=1.5, end=2.0, timestamp_source="provider"),
                        TranscriptWord(word="e", start=2.0, end=2.5, timestamp_source="provider"),
                        TranscriptWord(word="f", start=2.5, end=3.0, timestamp_source="provider"),
                    ],
                ),
            ],
        )
        edits = EditDecisionFile(
            edits=[EditDecision(type="delete", start=1.1, end=1.9, reason="x", source="semantic_dedup")]
        )

        out = remap_timeline(transcript, edits, tmp_path / "remapped.json")

        assert [seg.id for seg in out.segments] == ["s1_part1", "s1_part2"]
        assert [seg.text for seg in out.segments] == ["ab", "ef"]
        assert out.segments[1].start == pytest.approx(1.2)
