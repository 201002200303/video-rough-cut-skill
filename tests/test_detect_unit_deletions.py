from pathlib import Path

from schemas.models import TranscriptWord, UtteranceUnit
from scripts import detect_unit_deletions as module
from scripts.detect_unit_deletions import detect_unit_deletions


class FakeProvider:
    responses: list[dict] = []

    def semantic_dedup(self, prompt: str) -> dict:
        assert self.responses
        return self.responses.pop(0)


def _word(text, start, end):
    return TranscriptWord(word=text, start=start, end=end, timestamp_source="provider")


def _units():
    return [
        UtteranceUnit(
            unit_id="u-0001",
            start=0.0,
            end=1.0,
            text="前文",
            analysis_text="前文",
            source_segment_ids=["seg-001"],
            words=[_word("前", 0.0, 0.5), _word("文", 0.5, 1.0)],
            timestamp_source="provider",
        ),
        UtteranceUnit(
            unit_id="u-0002",
            start=1.2,
            end=2.0,
            text="重复口误",
            analysis_text="重复口误",
            source_segment_ids=["seg-002"],
            words=[_word("重", 1.2, 1.4), _word("复", 1.4, 1.6), _word("口", 1.6, 1.8), _word("误", 1.8, 2.0)],
            timestamp_source="provider",
        ),
        UtteranceUnit(
            unit_id="u-0003",
            start=2.2,
            end=3.0,
            text="后文",
            analysis_text="后文",
            source_segment_ids=["seg-003"],
            words=[_word("后", 2.2, 2.6), _word("文", 2.6, 3.0)],
            timestamp_source="provider",
        ),
    ]


def _prompts(tmp_path: Path):
    analysis = tmp_path / "analysis.md"
    deletion = tmp_path / "delete.md"
    continuity = tmp_path / "continuity.md"
    analysis.write_text("analysis", encoding="utf-8")
    deletion.write_text("delete", encoding="utf-8")
    continuity.write_text("continuity", encoding="utf-8")
    return analysis, deletion, continuity


def _patch(monkeypatch, responses):
    FakeProvider.responses = responses
    monkeypatch.setattr(module, "AliyunQwenProvider", lambda: FakeProvider())
    monkeypatch.setattr(
        module,
        "load_config",
        lambda: {
            "dedup": {
                "unit_delete_min_confidence": 0.9,
                "continuity_review_min_confidence": 0.9,
                "max_auto_delete_unit_duration": 4.0,
                "unit_llm_chunk_size": 24,
            }
        },
    )


def test_unit_delete_generates_whole_unit_edit_after_continuity_pass(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        [
            {"units": []},
            {"delete_units": [{"unit_id": "u-0002", "reason": "重复", "confidence": 0.95}]},
            {"pass": True, "confidence": 0.96, "reason": "自然"},
        ],
    )

    units, edits, reviews = detect_unit_deletions(_units(), *_prompts(tmp_path))

    assert len(units) == 3
    assert reviews == []
    assert len(edits) == 1
    assert edits[0].start == 1.2
    assert edits[0].end == 2.0
    assert "unit_delete" in edits[0].reason


def test_unit_delete_rejects_arbitrary_time_range(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        [
            {"units": []},
            {"delete_units": [{"unit_id": "u-0002", "start": 1.3, "end": 1.6, "confidence": 0.95}]},
        ],
    )

    _, edits, reviews = detect_unit_deletions(_units(), *_prompts(tmp_path))

    assert edits == []
    assert any(item["type"] == "unit_delete_rejected_arbitrary_time_range" for item in reviews)


def test_unit_delete_rejects_failed_continuity(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        [
            {"units": []},
            {"delete_units": [{"unit_id": "u-0002", "reason": "重复", "confidence": 0.95}]},
            {"pass": False, "confidence": 0.96, "reason": "删除后生硬"},
        ],
    )

    _, edits, reviews = detect_unit_deletions(_units(), *_prompts(tmp_path))

    assert edits == []
    assert any(item["type"] == "unit_delete_continuity_failed" for item in reviews)
