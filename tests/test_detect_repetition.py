from pathlib import Path

import pytest

from schemas.models import Transcript, TranscriptSegment, TranscriptWord
from scripts import detect_repetition as module
from scripts.detect_repetition import detect_repetition


class FakeProvider:
    responses: list[dict] = []

    def semantic_dedup(self, prompt: str) -> dict:
        assert self.responses
        return self.responses.pop(0)


def _word(text: str, start: float, end: float, source: str = "provider") -> TranscriptWord:
    return TranscriptWord(word=text, start=start, end=end, timestamp_source=source)


def _transcript(timestamp_source: str = "provider") -> Transcript:
    return Transcript(
        segments=[
            TranscriptSegment(
                id="seg-001",
                start=0.0,
                end=1.0,
                text="欢迎A",
                words=[
                    _word("欢", 0.0, 0.2, timestamp_source),
                    _word("迎", 0.2, 0.4, timestamp_source),
                    _word("A", 0.4, 1.0, timestamp_source),
                ],
            ),
            TranscriptSegment(
                id="seg-002",
                start=1.2,
                end=2.0,
                text="欢迎B",
                words=[
                    _word("欢", 1.2, 1.4, timestamp_source),
                    _word("迎", 1.4, 1.6, timestamp_source),
                    _word("B", 1.6, 2.0, timestamp_source),
                ],
            ),
            TranscriptSegment(
                id="seg-003",
                start=2.2,
                end=9.0,
                text="有效内容",
                words=[_word("有效", 2.2, 4.0, timestamp_source), _word("内容", 4.0, 9.0, timestamp_source)],
            ),
        ]
    )


def _semantic_segments() -> list[dict]:
    return [
        {
            "segment_id": "s_000",
            "start": 0.0,
            "end": 9.0,
            "text": "欢迎A欢迎B有效内容",
            "source_segment_ids": ["seg-001", "seg-002", "seg-003"],
        },
        {
            "segment_id": "s_001",
            "start": 10.0,
            "end": 15.0,
            "text": "后文更完整",
            "source_segment_ids": [],
        },
    ]


def _prompt(tmp_path: Path) -> Path:
    path = tmp_path / "semantic.md"
    path.write_text("semantic prompt", encoding="utf-8")
    (tmp_path / "local_semantic_dedup.md").write_text("local prompt", encoding="utf-8")
    return path


def _patch_provider(monkeypatch, responses: list[dict]) -> None:
    FakeProvider.responses = responses
    monkeypatch.setattr(module, "AliyunQwenProvider", lambda: FakeProvider())


def test_long_duplicate_refines_to_local_delete(monkeypatch, tmp_path: Path):
    _patch_provider(
        monkeypatch,
        [
            {
                "duplicate_groups": [
                    {
                        "keep_segment_id": "s_001",
                        "delete_segment_ids": ["s_000"],
                        "reason": "粗段过长但包含局部重复",
                        "confidence": 0.95,
                    }
                ]
            },
            {
                "delete_ranges": [
                    {
                        "segment_id": "seg-002",
                        "start": 1.6,
                        "end": 2.0,
                        "reason": "重复欢迎称呼",
                        "confidence": 0.93,
                    }
                ],
                "review_needed": [],
            },
        ],
    )

    edits, reviews = detect_repetition(
        _semantic_segments(),
        _prompt(tmp_path),
        max_auto_delete_duration=4.0,
        transcript=_transcript(),
    )

    assert len(edits) == 1
    assert edits[0].type == "delete"
    assert edits[0].source == "semantic_dedup"
    assert edits[0].start == pytest.approx(1.68)
    assert edits[0].end == pytest.approx(1.92)
    assert "local_refine" in edits[0].reason
    assert any(item["type"] == "duplicate_long_refined" for item in reviews)


def test_local_refine_rejects_too_long_range(monkeypatch, tmp_path: Path):
    _patch_provider(
        monkeypatch,
        [
            {
                "duplicate_groups": [
                    {"keep_segment_id": "s_001", "delete_segment_ids": ["s_000"], "confidence": 0.95}
                ]
            },
            {"delete_ranges": [{"segment_id": "seg-003", "start": 2.2, "end": 9.0, "confidence": 0.99}]},
        ],
    )

    edits, reviews = detect_repetition(
        _semantic_segments(),
        _prompt(tmp_path),
        max_auto_delete_duration=4.0,
        transcript=_transcript(),
    )

    assert edits == []
    assert any(item["type"] == "local_refine_delete_too_long" for item in reviews)


def test_local_refine_rejects_low_confidence(monkeypatch, tmp_path: Path):
    _patch_provider(
        monkeypatch,
        [
            {
                "duplicate_groups": [
                    {"keep_segment_id": "s_001", "delete_segment_ids": ["s_000"], "confidence": 0.95}
                ]
            },
            {"delete_ranges": [{"segment_id": "seg-002", "start": 1.6, "end": 2.0, "confidence": 0.5}]},
        ],
    )

    edits, reviews = detect_repetition(
        _semantic_segments(),
        _prompt(tmp_path),
        max_auto_delete_duration=4.0,
        transcript=_transcript(),
    )

    assert edits == []
    assert any(item["type"] == "local_refine_low_confidence" for item in reviews)


def test_local_refine_respects_total_delete_limit(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        module,
        "load_config",
        lambda: {"dedup": {"local_refine_max_total_delete_duration_per_semantic_segment": 1.1}},
    )
    _patch_provider(
        monkeypatch,
        [
            {
                "duplicate_groups": [
                    {"keep_segment_id": "s_001", "delete_segment_ids": ["s_000"], "confidence": 0.95}
                ]
            },
            {
                "delete_ranges": [
                    {"segment_id": "seg-001", "start": 0.0, "end": 1.0, "confidence": 0.95},
                    {"segment_id": "seg-002", "start": 1.2, "end": 2.0, "confidence": 0.95},
                ]
            },
        ],
    )

    edits, reviews = detect_repetition(
        _semantic_segments(),
        _prompt(tmp_path),
        max_auto_delete_duration=4.0,
        transcript=_transcript(),
    )

    assert len(edits) == 1
    assert any(item["type"] == "local_refine_total_delete_too_long" for item in reviews)


def test_local_refine_rejects_multiple_ranges_in_same_segment(monkeypatch, tmp_path: Path):
    _patch_provider(
        monkeypatch,
        [
            {
                "duplicate_groups": [
                    {"keep_segment_id": "s_001", "delete_segment_ids": ["s_000"], "confidence": 0.95}
                ]
            },
            {
                "delete_ranges": [
                    {"segment_id": "seg-002", "start": 1.2, "end": 1.4, "confidence": 0.95},
                    {"segment_id": "seg-002", "start": 1.6, "end": 2.0, "confidence": 0.95},
                ]
            },
        ],
    )

    edits, reviews = detect_repetition(
        _semantic_segments(),
        _prompt(tmp_path),
        max_auto_delete_duration=4.0,
        transcript=_transcript(),
    )

    assert edits == []
    assert any(item["type"] == "local_refine_multiple_ranges_same_segment" for item in reviews)


def test_local_refine_rejects_delete_that_leaves_short_fragment(monkeypatch, tmp_path: Path):
    _patch_provider(
        monkeypatch,
        [
            {
                "duplicate_groups": [
                    {"keep_segment_id": "s_001", "delete_segment_ids": ["s_000"], "confidence": 0.95}
                ]
            },
            {
                "delete_ranges": [
                    {"segment_id": "seg-002", "start": 1.4, "end": 1.6, "confidence": 0.95},
                ]
            },
        ],
    )

    edits, reviews = detect_repetition(
        _semantic_segments(),
        _prompt(tmp_path),
        max_auto_delete_duration=4.0,
        transcript=_transcript(),
    )

    assert edits == []
    assert any(item["type"] == "local_refine_would_leave_short_fragment" for item in reviews)


def test_local_refine_requires_provider_timestamps(monkeypatch, tmp_path: Path):
    _patch_provider(
        monkeypatch,
        [
            {
                "duplicate_groups": [
                    {"keep_segment_id": "s_001", "delete_segment_ids": ["s_000"], "confidence": 0.95}
                ]
            }
        ],
    )

    edits, reviews = detect_repetition(
        _semantic_segments(),
        _prompt(tmp_path),
        max_auto_delete_duration=4.0,
        transcript=_transcript(timestamp_source="estimated"),
    )

    assert edits == []
    assert any(item["type"] == "local_refine_requires_provider_timestamps" for item in reviews)


def test_review_needed_segment_can_trigger_local_refine(monkeypatch, tmp_path: Path):
    _patch_provider(
        monkeypatch,
        [
            {"duplicate_groups": [], "review_needed": ["s_000"]},
            {
                "delete_ranges": [
                    {
                        "segment_id": "seg-002",
                        "start": 1.6,
                        "end": 2.0,
                        "reason": "review 段内发现重复欢迎称呼",
                        "confidence": 0.94,
                    }
                ],
                "review_needed": [],
            },
        ],
    )

    edits, reviews = detect_repetition(
        _semantic_segments(),
        _prompt(tmp_path),
        max_auto_delete_duration=4.0,
        transcript=_transcript(),
    )

    assert len(edits) == 1
    assert edits[0].source == "semantic_dedup"
    assert any(item["type"] == "provider_review_refined" for item in reviews)
