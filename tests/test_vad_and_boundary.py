"""VAD 与 LLM 删除边界解析测试。"""

from schemas.edit_decision import EditDecision
from schemas.transcript import Transcript, TranscriptSegment, TranscriptWord
from scripts.detect_vad import _parse_silences, _silences_to_speech
from scripts.resolve_edit_boundaries import resolve_edit_boundaries


def test_parse_silencedetect_output():
    stderr = """
    [silencedetect] silence_start: 1.25
    [silencedetect] silence_end: 2.00 | silence_duration: 0.75
    """
    assert _parse_silences(stderr) == [(1.25, 2.0)]


def test_silences_to_speech_segments():
    speech = _silences_to_speech([(1.0, 2.0), (4.0, 4.5)], duration=6.0, min_speech_duration=0.2)
    assert speech == [
        {"start": 0.0, "end": 1.0, "duration": 1.0},
        {"start": 2.0, "end": 4.0, "duration": 2.0},
        {"start": 4.5, "end": 6.0, "duration": 1.5},
    ]


def test_estimated_llm_delete_goes_to_review():
    transcript = Transcript(
        segments=[
            TranscriptSegment(
                id="s1",
                start=0.0,
                end=2.0,
                text="嗯",
                words=[TranscriptWord(word="嗯", start=0.0, end=2.0, timestamp_source="estimated")],
            )
        ]
    )
    edits = [EditDecision(type="delete", start=0.0, end=2.0, reason="语气词", source="content_cleanup")]
    safe, review = resolve_edit_boundaries(edits, transcript, {}, [])
    assert safe == []
    assert review[0]["type"] == "llm_delete_requires_provider_timestamp"


def test_high_confidence_short_estimated_cleanup_can_pass():
    transcript = Transcript(
        segments=[
            TranscriptSegment(
                id="s1",
                start=0.0,
                end=2.0,
                text="嗯",
                words=[TranscriptWord(word="嗯", start=0.0, end=1.0, timestamp_source="estimated")],
            )
        ]
    )
    edits = [
        EditDecision(
            type="delete",
            start=0.0,
            end=1.0,
            reason="高置信语气词",
            source="content_cleanup",
            confidence=0.98,
        )
    ]
    safe, review = resolve_edit_boundaries(edits, transcript, {}, [])
    assert review == []
    assert safe[0].source == "content_cleanup"
    assert "estimated timestamp" in safe[0].reason


def test_provider_llm_delete_can_align_to_vad():
    transcript = Transcript(
        segments=[
            TranscriptSegment(
                id="s1",
                start=0.0,
                end=2.0,
                text="嗯",
                words=[TranscriptWord(word="嗯", start=0.2, end=1.8, timestamp_source="provider")],
            )
        ]
    )
    vad = {"silence_segments": [{"start": 0.1, "end": 0.2}, {"start": 1.8, "end": 1.9}]}
    edits = [EditDecision(type="delete", start=0.2, end=1.8, reason="语气词", source="content_cleanup")]
    safe, review = resolve_edit_boundaries(edits, transcript, vad, [])
    assert review == []
    assert safe[0].start == 0.2
    assert safe[0].end == 1.8
