from schemas.models import Transcript, TranscriptSegment, TranscriptWord
from scripts.split_transcript_segments import split_transcript_segments_on_word_gaps


def _word(text: str, start: float, end: float) -> TranscriptWord:
    return TranscriptWord(word=text, start=start, end=end, timestamp_source="provider")


def test_split_transcript_segment_on_long_word_gap(tmp_path):
    transcript = Transcript(
        language="zh",
        segments=[
            TranscriptSegment(
                id="seg-030",
                start=82.67,
                end=88.82,
                text="创新药国产创新药出口国产创新奥出海迎增长态势。",
                words=[
                    _word("创", 82.67, 82.91),
                    _word("新", 82.97, 83.15),
                    _word("药", 83.15, 83.39),
                    _word("国", 83.89, 84.13),
                    _word("产", 84.17, 84.37),
                    _word("创", 84.37, 84.53),
                    _word("新", 84.53, 84.71),
                    _word("药", 84.71, 84.95),
                    _word("出", 84.95, 85.19),
                    _word("口", 85.19, 85.575),
                    _word("国", 86.48, 86.68),
                    _word("产", 86.68, 86.88),
                    _word("创", 86.88, 87.04),
                    _word("新", 87.04, 87.2),
                    _word("奥", 87.2, 87.38),
                    _word("出", 87.38, 87.56),
                    _word("海", 87.56, 87.8),
                    _word("迎", 87.86, 88.1),
                    _word("增", 88.12, 88.28),
                    _word("长", 88.28, 88.48),
                    _word("态", 88.48, 88.58),
                    _word("势", 88.58, 88.82),
                ],
            )
        ],
    )

    out = tmp_path / "transcript.json"
    split = split_transcript_segments_on_word_gaps(
        transcript,
        out,
        word_gap_threshold=0.65,
        min_segment_duration=0.35,
        min_segment_chars=2,
    )

    assert [seg.id for seg in split.segments] == ["seg-030_part1", "seg-030_part2"]
    assert split.segments[0].text == "创新药国产创新药出口"
    assert split.segments[0].start == 82.67
    assert split.segments[0].end == 85.575
    assert split.segments[1].text == "国产创新奥出海迎增长态势"
    assert split.segments[1].start == 86.48
    assert split.segments[1].end == 88.82
    assert out.exists()


def test_split_transcript_segment_ignores_estimated_timestamps():
    transcript = Transcript(
        language="zh",
        segments=[
            TranscriptSegment(
                id="seg-001",
                start=0.0,
                end=2.0,
                text="不要拆",
                words=[
                    TranscriptWord(word="不", start=0.0, end=0.2, timestamp_source="estimated"),
                    TranscriptWord(word="拆", start=1.2, end=1.5, timestamp_source="estimated"),
                ],
            )
        ],
    )

    split = split_transcript_segments_on_word_gaps(transcript, word_gap_threshold=0.65)

    assert split.segments[0].id == "seg-001"
    assert split.segments[0].text == "不要拆"
