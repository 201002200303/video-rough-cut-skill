"""剪辑前后逐句时间轴调试文件测试。"""

from schemas.models import EditDecision, EditDecisionFile
from schemas.models import Transcript, TranscriptSegment, TranscriptWord
from scripts.generate_transcript_debug import generate_transcript_debug_files


def test_generate_transcript_debug_files(tmp_path):
    before = Transcript(
        segments=[
            TranscriptSegment(
                id="s1",
                start=0.0,
                end=2.0,
                text="你好嗯",
                words=[
                    TranscriptWord(word="你好", start=0.0, end=1.0, timestamp_source="provider"),
                    TranscriptWord(word="嗯", start=1.0, end=2.0, timestamp_source="provider"),
                ],
            )
        ]
    )
    after = Transcript(
        segments=[
            TranscriptSegment(
                id="s1",
                start=0.0,
                end=1.0,
                text="你好",
                words=[TranscriptWord(word="你好", start=0.0, end=1.0, timestamp_source="provider")],
            )
        ]
    )
    edits = EditDecisionFile(
        edits=[EditDecision(type="delete", start=1.0, end=2.0, reason="语气词", source="content_cleanup")]
    )
    before_path, after_path = generate_transcript_debug_files(
        before,
        after,
        edits,
        tmp_path / "before.md",
        tmp_path / "after.md",
    )
    before_text = before_path.read_text(encoding="utf-8")
    after_text = after_path.read_text(encoding="utf-8")
    assert "剪辑前逐句时间轴" in before_text
    assert "剪辑后逐句时间轴" in after_text
    assert "实际剪辑策略" in before_text
    assert "判断标准" in after_text
    assert "1.000-2.000" in before_text
