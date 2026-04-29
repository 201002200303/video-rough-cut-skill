"""ASS 字幕生成测试。"""

from schemas.transcript import Transcript, TranscriptSegment
from scripts.generate_subtitles import generate_subtitles


class TestSubtitleASS:
    def test_generate_ass_contains_style_and_dialogue(self, tmp_path):
        transcript = Transcript(
            language="zh",
            segments=[TranscriptSegment(id="s1", start=0.0, end=1.2, text="这是一段测试字幕文本", words=[])],
        )
        out = tmp_path / "subtitles.ass"
        generate_subtitles(transcript, out)
        text = out.read_text(encoding="utf-8")
        assert "Style: Default" in text
        assert "Dialogue:" in text
        assert "&H0000FFFF" in text