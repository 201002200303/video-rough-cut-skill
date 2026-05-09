import pytest

from schemas.models import Transcript, TranscriptSegment, TranscriptWord
from scripts.build_utterance_units import build_utterance_units


def _word(text, start, end):
    return TranscriptWord(word=text, start=start, end=end, timestamp_source="provider")


def test_word_gap_splits_utterance_units_on_provider_boundaries():
    transcript = Transcript(
        segments=[
            TranscriptSegment(
                id="seg-001",
                start=0.0,
                end=3.0,
                text="你好继续",
                words=[
                    _word("你", 0.0, 0.2),
                    _word("好", 0.2, 0.4),
                    _word("继", 1.0, 1.2),
                    _word("续", 1.2, 1.4),
                ],
            )
        ]
    )

    units = build_utterance_units(transcript, word_gap_split_threshold=0.45)

    assert [u.text for u in units] == ["你好", "继续"]
    assert units[0].start == pytest.approx(0.0)
    assert units[0].end == pytest.approx(0.4)
    assert units[1].start == pytest.approx(1.0)
    assert units[1].end == pytest.approx(1.4)
    assert all(u.timestamp_source == "provider" for u in units)


def test_utterance_unit_skips_too_short_chunks():
    transcript = Transcript(
        segments=[
            TranscriptSegment(
                id="seg-001",
                start=0.0,
                end=1.0,
                text="嗯",
                words=[_word("嗯", 0.0, 0.2)],
            )
        ]
    )

    units = build_utterance_units(transcript, min_duration=0.35)

    assert units == []
