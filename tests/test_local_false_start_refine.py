from pathlib import Path

from schemas.models import TranscriptWord, UtteranceUnit
from scripts import detect_local_false_start_refine as module
from scripts.detect_local_false_start_refine import detect_local_false_start_repairs


class FakeProvider:
    responses: list[dict] = []

    def semantic_dedup(self, prompt: str) -> dict:
        assert self.responses
        return self.responses.pop(0)


def _word(text: str, start: float, end: float) -> TranscriptWord:
    return TranscriptWord(word=text, start=start, end=end, timestamp_source="provider")


def _prompts(tmp_path: Path):
    refine = tmp_path / "refine.md"
    continuity = tmp_path / "continuity.md"
    refine.write_text("refine", encoding="utf-8")
    continuity.write_text("continuity", encoding="utf-8")
    return refine, continuity


def _patch(monkeypatch, responses):
    FakeProvider.responses = responses
    monkeypatch.setattr(module, "AliyunQwenProvider", lambda: FakeProvider())
    monkeypatch.setattr(
        module,
        "load_config",
        lambda: {
            "local_false_start_refine": {
                "enabled": True,
                "min_confidence": 0.92,
                "continuity_min_confidence": 0.9,
                "max_delete_duration": 4.0,
                "max_window_units_before": 1,
                "max_window_units_after": 2,
                "min_remaining_chars": 1,
                "allow_multiple_ranges": False,
            }
        },
    )


def test_failed_unit_review_can_refine_to_word_range(monkeypatch, tmp_path):
    units = [
        UtteranceUnit(
            unit_id="u-0045",
            start=99.6,
            end=102.88,
            text="还有一个根本的原因就是业绩假期一大批",
            analysis_text="还有一个根本的原因就是业绩暴雷一大批",
            source_segment_ids=["seg-042_part1"],
            words=[
                _word("还", 99.6, 99.76),
                _word("有", 99.76, 99.9),
                _word("一", 99.9, 100.0),
                _word("个", 100.0, 100.1),
                _word("根", 100.1, 100.18),
                _word("本", 100.18, 100.3),
                _word("的", 100.3, 100.44),
                _word("原", 100.44, 100.54),
                _word("因", 100.54, 100.78),
                _word("就", 100.94, 101.14),
                _word("是", 101.14, 101.26),
                _word("业", 101.26, 101.44),
                _word("绩", 101.44, 101.68),
                _word("假", 101.94, 102.16),
                _word("期", 102.16, 102.4),
                _word("一", 102.4, 102.52),
                _word("大", 102.52, 102.64),
                _word("批", 102.64, 102.88),
            ],
            timestamp_source="provider",
        ),
        UtteranceUnit(
            unit_id="u-0046",
            start=103.52,
            end=104.02,
            text="假期",
            analysis_text="暴雷",
            source_segment_ids=["seg-042_part2"],
            words=[_word("假", 103.52, 103.76), _word("期", 103.78, 104.02)],
            timestamp_source="provider",
        ),
        UtteranceUnit(
            unit_id="u-0047",
            start=104.1,
            end=105.56,
            text="一大批股票集体爆雷",
            analysis_text="一大批股票集体爆雷",
            source_segment_ids=["seg-043"],
            words=[
                _word("一", 104.1, 104.2),
                _word("大", 104.2, 104.38),
                _word("批", 104.38, 104.58),
                _word("股", 104.58, 104.76),
                _word("票", 104.76, 104.94),
                _word("集", 104.94, 105.1),
                _word("体", 105.1, 105.24),
                _word("爆", 105.24, 105.4),
                _word("雷", 105.4, 105.56),
            ],
            timestamp_source="provider",
        ),
    ]
    reviews = [
        {
            "type": "unit_delete_continuity_failed",
            "unit_id": "u-0046",
            "text": "假期",
            "analysis_text": "暴雷",
            "candidate_reason": "明显口误，后文完整重述",
            "continuity": {"reason": "只删假期后仍然残句"},
        }
    ]
    _patch(
        monkeypatch,
        [
            {
                "delete_word_ranges": [
                    {
                        "start_word_id": "w-0012",
                        "end_word_id": "w-0020",
                        "reason": "前半句改口后重启",
                        "confidence": 0.95,
                    }
                ]
            },
            {"pass": True, "confidence": 0.96, "reason": "删除后自然"},
        ],
    )

    edits, updated_reviews = detect_local_false_start_repairs(units, reviews, *_prompts(tmp_path))

    assert updated_reviews == []
    assert len(edits) == 1
    assert edits[0].start == 101.26
    assert edits[0].end == 104.02
    assert edits[0].source == "local_false_start_refine"


def test_refine_keeps_review_when_continuity_fails(monkeypatch, tmp_path):
    units = [
        UtteranceUnit(
            unit_id="u-0001",
            start=0.0,
            end=1.0,
            text="明显口误",
            analysis_text="明显口误",
            source_segment_ids=["s1"],
            words=[_word("明", 0.0, 0.2), _word("显", 0.2, 0.4), _word("口", 0.4, 0.6), _word("误", 0.6, 1.0)],
            timestamp_source="provider",
        )
    ]
    reviews = [
        {
            "type": "unit_delete_continuity_failed",
            "unit_id": "u-0001",
            "text": "明显口误",
            "analysis_text": "明显口误",
            "candidate_reason": "明显口误",
            "continuity": {"reason": "删除不自然"},
        }
    ]
    _patch(
        monkeypatch,
        [
            {
                "delete_word_ranges": [
                    {"start_word_id": "w-0001", "end_word_id": "w-0002", "reason": "口误", "confidence": 0.95}
                ]
            },
            {"pass": False, "confidence": 0.96, "reason": "仍不自然"},
        ],
    )

    edits, updated_reviews = detect_local_false_start_repairs(units, reviews, *_prompts(tmp_path))

    assert edits == []
    assert updated_reviews[0]["type"] == "unit_delete_continuity_failed"
    assert updated_reviews[0]["local_refine_reviews"]
