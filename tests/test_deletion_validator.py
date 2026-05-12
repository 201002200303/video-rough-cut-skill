"""删除候选硬校验器测试。"""

import pytest

from schemas.models import DeletionCandidate, SourceWord
from validators.deletion_validator import resolve_deletion_times, validate_deletion_candidates


def _sw(word_id, char, start, end, segment_id="seg-001", ts="provider"):
    return SourceWord(word_id=word_id, char=char, start=start, end=end, segment_id=segment_id, timestamp_source=ts)


class TestDeletionValidator:
    def test_accepts_valid_false_start(self):
        words = [
            _sw("w-0001", "我", 0.0, 0.2),
            _sw("w-0002", "觉", 0.2, 0.4),
            _sw("w-0003", "得", 0.4, 0.6),
            _sw("w-0004", "不", 0.6, 0.8),
            _sw("w-0005", "是", 0.8, 1.0),
        ]
        candidates = [
            DeletionCandidate(
                candidate_id="del-001", window_id="win-000",
                type="false_start",
                word_ids=["w-0001", "w-0002", "w-0003", "w-0004", "w-0005"],
                delete_text_original="我觉得不是",
                reason="残句", confidence=0.90,
            )
        ]
        result = validate_deletion_candidates(candidates, words)
        assert len(result.accepted) == 1

    def test_rejects_estimated_timestamps(self):
        words = [
            _sw("w-0001", "我", 0.0, 0.2, ts="estimated"),
            _sw("w-0002", "觉", 0.2, 0.4, ts="estimated"),
        ]
        candidates = [
            DeletionCandidate(
                candidate_id="del-001", window_id="win-000",
                type="false_start",
                word_ids=["w-0001", "w-0002"],
                delete_text_original="我觉", reason="残句", confidence=0.90,
            )
        ]
        result = validate_deletion_candidates(candidates, words)
        assert len(result.accepted) == 0
        assert len(result.rejected) == 1

    def test_rejects_nonexistent_word_ids(self):
        words = [_sw("w-0001", "你", 0.0, 0.2)]
        candidates = [
            DeletionCandidate(
                candidate_id="del-001", window_id="win-000",
                type="false_start",
                word_ids=["w-9999"],
                delete_text_original="x", reason="x", confidence=0.90,
            )
        ]
        result = validate_deletion_candidates(candidates, words)
        assert len(result.rejected) == 1

    def test_rejects_low_confidence(self):
        words = [_sw("w-0001", "嗯", 0.0, 0.2)]
        candidates = [
            DeletionCandidate(
                candidate_id="del-001", window_id="win-000",
                type="filler_phrase",
                word_ids=["w-0001"],
                delete_text_original="嗯", reason="filler", confidence=0.50,
            )
        ]
        result = validate_deletion_candidates(candidates, words)
        assert len(result.rejected) == 1

    def test_rejects_empty_word_ids(self):
        words = [_sw("w-0001", "你", 0.0, 0.2)]
        candidates = [
            DeletionCandidate(
                candidate_id="del-001", window_id="win-000",
                type="false_start",
                word_ids=[],
                delete_text_original="", reason="empty", confidence=0.90,
            )
        ]
        result = validate_deletion_candidates(candidates, words)
        assert len(result.rejected) == 1

    def test_rejects_long_filler_phrase(self):
        words = [
            _sw("w-0001", "然", 0.0, 0.2),
            _sw("w-0002", "后", 0.2, 0.4),
            _sw("w-0003", "然", 0.4, 0.6),
            _sw("w-0004", "后", 0.6, 0.8),
            _sw("w-0005", "我", 0.8, 1.0),
        ]
        candidates = [
            DeletionCandidate(
                candidate_id="del-001", window_id="win-000",
                type="filler_phrase",
                word_ids=["w-0001", "w-0002", "w-0003", "w-0004", "w-0005"],
                delete_text_original="然后然后我", reason="filler", confidence=0.92,
            )
        ]
        result = validate_deletion_candidates(candidates, words)
        # 5 chars > 4 char limit for filler_phrase
        assert len(result.rejected) == 1

    def test_resolve_deletion_times(self):
        words = {
            "w-0001": _sw("w-0001", "我", 1.0, 1.3),
            "w-0002": _sw("w-0002", "觉", 1.3, 1.5),
        }
        dc = DeletionCandidate(
            candidate_id="del-001", window_id="win-000",
            type="false_start",
            word_ids=["w-0001", "w-0002"],
            delete_text_original="我觉", reason="test", confidence=0.90,
        )
        start, end = resolve_deletion_times(dc, words, padding_before=0.06, padding_after=0.08)
        assert start == pytest.approx(0.94)
        assert end == pytest.approx(1.58)

    def test_accepts_fast_repetition_with_provider_timestamps(self):
        words = [
            _sw("w-0001", "这", 0.0, 0.15),
            _sw("w-0002", "个", 0.15, 0.30),
            _sw("w-0003", "这", 0.30, 0.45),
            _sw("w-0004", "个", 0.45, 0.60),
            _sw("w-0005", "地", 0.60, 0.75),
        ]
        candidates = [
            DeletionCandidate(
                candidate_id="del-001", window_id="win-000",
                type="fast_repetition",
                word_ids=["w-0003", "w-0004"],
                delete_text_original="这个", reason="快速重复", confidence=0.94,
            )
        ]
        result = validate_deletion_candidates(candidates, words)
        assert len(result.accepted) == 1
