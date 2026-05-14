from schemas.models import DisplayPatch, Transcript, TranscriptSegment, TranscriptWord
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
        assert "&H00FFFFFF" in text

    def test_display_patch_insert_with_word_ids(self, tmp_path):
        """insert_display 在段内有 word_id 时应写入字幕（与 apply_display_patches 一致）。"""
        transcript = Transcript(
            language="zh",
            segments=[
                TranscriptSegment(
                    id="seg-1",
                    start=0.0,
                    end=2.0,
                    text="国家统计放大招",
                    words=[
                        TranscriptWord(word="国", start=0.0, end=0.1, timestamp_source="provider", word_id="w-0001"),
                        TranscriptWord(word="家", start=0.1, end=0.2, timestamp_source="provider", word_id="w-0002"),
                        TranscriptWord(word="统", start=0.2, end=0.3, timestamp_source="provider", word_id="w-0003"),
                        TranscriptWord(word="计", start=0.3, end=0.4, timestamp_source="provider", word_id="w-0004"),
                        TranscriptWord(word="放", start=0.4, end=0.5, timestamp_source="provider", word_id="w-0005"),
                        TranscriptWord(word="大", start=0.5, end=0.6, timestamp_source="provider", word_id="w-0006"),
                        TranscriptWord(word="招", start=0.6, end=0.7, timestamp_source="provider", word_id="w-0007"),
                    ],
                )
            ],
        )
        patches = [
            DisplayPatch(
                patch_id="dp-1",
                type="insert_display",
                word_ids=[],
                after_word_id="w-0004",
                from_text="",
                to_text="局",
                confidence=0.95,
                evidence={},
            )
        ]
        out = tmp_path / "sub.ass"
        generate_subtitles(transcript, out, display_patches=patches)
        ass = out.read_text(encoding="utf-8")
        assert "国家统计局" in ass
