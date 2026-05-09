import json

from schemas.models import Transcript, TranscriptSegment, TranscriptWord, UtteranceUnit
from scripts import correct_subtitles


class FakeProvider:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.prompts = []

    def semantic_dedup(self, prompt):
        self.prompts.append(prompt)
        if self.exc:
            raise self.exc
        return self.result


def _transcript():
    return Transcript(
        language="zh",
        segments=[
            TranscriptSegment(
                id="seg-001",
                start=1.0,
                end=2.0,
                text="国产创新奥",
                words=[TranscriptWord(word="国产", start=1.0, end=1.4, timestamp_source="provider")],
            )
        ],
    )


def test_correct_subtitle_text_preserves_timestamps_and_words(monkeypatch, tmp_path):
    monkeypatch.setattr(
        correct_subtitles,
        "load_config",
        lambda: {"subtitle_correction": {"enabled": True, "max_segment_chars": 120, "max_length_ratio": 1.6}},
    )
    monkeypatch.setattr(
        correct_subtitles,
        "AliyunQwenProvider",
        lambda: FakeProvider({"segments": [{"segment_id": "seg-001", "text": "国产创新药"}]}),
    )
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")

    corrected = correct_subtitles.correct_subtitle_text(_transcript(), prompt)

    assert corrected.segments[0].text == "国产创新药"
    assert corrected.segments[0].start == 1.0
    assert corrected.segments[0].end == 2.0
    assert corrected.segments[0].words[0].timestamp_source == "provider"


def test_correct_subtitle_text_rejects_too_long_correction(monkeypatch, tmp_path):
    monkeypatch.setattr(
        correct_subtitles,
        "load_config",
        lambda: {"subtitle_correction": {"enabled": True, "max_segment_chars": 120, "max_length_ratio": 1.2}},
    )
    monkeypatch.setattr(
        correct_subtitles,
        "AliyunQwenProvider",
        lambda: FakeProvider({"segments": [{"segment_id": "seg-001", "text": "国产创新药需要长期持续关注"}]}),
    )
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")

    corrected = correct_subtitles.correct_subtitle_text(_transcript(), prompt)

    assert corrected.segments[0].text == "国产创新奥"


def test_correct_subtitle_text_rejects_low_similarity_correction(monkeypatch, tmp_path):
    monkeypatch.setattr(
        correct_subtitles,
        "load_config",
        lambda: {
            "subtitle_correction": {
                "enabled": True,
                "max_segment_chars": 120,
                "max_length_ratio": 2.0,
                "min_similarity": 0.45,
            }
        },
    )
    monkeypatch.setattr(
        correct_subtitles,
        "AliyunQwenProvider",
        lambda: FakeProvider({"segments": [{"segment_id": "seg-001", "text": "但是这里我要提醒大家"}]}),
    )
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")

    corrected = correct_subtitles.correct_subtitle_text(_transcript(), prompt)

    assert corrected.segments[0].text == "国产创新奥"


def test_correct_subtitle_text_rejects_changed_number_phrase(monkeypatch, tmp_path):
    monkeypatch.setattr(
        correct_subtitles,
        "load_config",
        lambda: {
            "subtitle_correction": {
                "enabled": True,
                "max_segment_chars": 120,
                "max_length_ratio": 2.0,
                "min_similarity": 0.45,
            }
        },
    )
    monkeypatch.setattr(
        correct_subtitles,
        "AliyunQwenProvider",
        lambda: FakeProvider({"segments": [{"segment_id": "seg-001", "text": "今年授权金额超过五十七亿美元"}]}),
    )
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")
    original = Transcript(
        language="zh",
        segments=[
            TranscriptSegment(
                id="seg-001",
                start=1.0,
                end=2.0,
                text="今年授权金额超过五百七十美元",
                words=[],
            )
        ],
    )

    corrected = correct_subtitles.correct_subtitle_text(original, prompt)

    assert corrected.segments[0].text == "今年授权金额超过五百七十美元"


def test_correct_subtitle_text_falls_back_on_provider_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        correct_subtitles,
        "load_config",
        lambda: {"subtitle_correction": {"enabled": True}},
    )
    monkeypatch.setattr(
        correct_subtitles,
        "AliyunQwenProvider",
        lambda: FakeProvider(exc=RuntimeError("boom")),
    )
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")
    original = _transcript()

    corrected = correct_subtitles.correct_subtitle_text(original, prompt)

    assert corrected == original


def test_correct_subtitle_text_sends_context_and_reference_units(monkeypatch, tmp_path):
    monkeypatch.setattr(
        correct_subtitles,
        "load_config",
        lambda: {
            "subtitle_correction": {
                "enabled": True,
                "max_segment_chars": 120,
                "max_length_ratio": 1.6,
                "min_similarity": 0.35,
                "context_segments": 1,
                "max_context_chars": 80,
            }
        },
    )
    provider = FakeProvider({"segments": [{"segment_id": "seg-018_part2", "text": "上面也送来了定心丸"}]})
    monkeypatch.setattr(correct_subtitles, "AliyunQwenProvider", lambda: provider)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")
    transcript = Transcript(
        language="zh",
        segments=[
            TranscriptSegment(id="seg-017", start=0.0, end=1.0, text="那上涨才有底气啊", words=[]),
            TranscriptSegment(id="seg-018_part2", start=1.1, end=2.0, text="上面也送来了定性晚", words=[]),
            TranscriptSegment(id="seg-019", start=2.2, end=3.0, text="政府会明确表示要支持资金入市", words=[]),
        ],
    )
    units = [
        UtteranceUnit(
            unit_id="u-0019",
            start=1.1,
            end=2.0,
            text="上面也送来了定性晚",
            analysis_text="上面也送来了定心丸，",
            source_segment_ids=["seg-018_part2"],
            words=[],
        )
    ]

    corrected = correct_subtitles.correct_subtitle_text(transcript, prompt, reference_units=units)
    payload = json.loads(provider.prompts[0].rsplit("\n", 1)[-1])
    target = payload["segments"][1]

    assert target["context_before"] == "那上涨才有底气啊"
    assert target["context_after"] == "政府会明确表示要支持资金入市"
    assert target["reference_text"] == "上面也送来了定心丸，"
    assert corrected.segments[1].text == "上面也送来了定心丸"
