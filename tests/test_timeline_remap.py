"""时间线重映射逻辑测试。"""

from schemas.edit_decision import EditDecision, EditDecisionFile
from schemas.transcript import Transcript, TranscriptSegment
from scripts.remap_timeline import remap_timeline


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