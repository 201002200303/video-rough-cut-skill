"""硬校验器测试 — 纯代码校验，不依赖 LLM。"""

import pytest

from schemas.models import CorrectionCandidate, DisplayPatch, SourceWord
from validators.correction_validator import apply_display_patches, validate_display_patches


def _sw(word_id, char, start, end, segment_id="seg-001", ts="provider"):
    return SourceWord(word_id=word_id, char=char, start=start, end=end, segment_id=segment_id, timestamp_source=ts)


class TestCorrectionValidator:
    def test_accepts_valid_replace_display(self):
        words = [
            _sw("w-0001", "板", 0.0, 0.2),
            _sw("w-0002", "也", 0.2, 0.4),
            _sw("w-0003", "今", 0.4, 0.6),
        ]
        candidates = [
            CorrectionCandidate(
                window_id="win-000", type="replace_display",
                word_ids=["w-0002"], from_text="也", to_text="姐", confidence=0.93,
            )
        ]
        result = validate_display_patches(candidates, words)
        assert len(result.accepted) == 1
        assert result.accepted[0].to_text == "姐"

    def test_rejects_low_confidence(self):
        words = [_sw("w-0001", "板", 0.0, 0.2)]
        candidates = [
            CorrectionCandidate(
                window_id="win-000", type="replace_display",
                word_ids=["w-0001"], from_text="板", to_text="版", confidence=0.50,
            )
        ]
        result = validate_display_patches(candidates, words)
        assert len(result.accepted) == 0
        assert len(result.rejected) == 1

    def test_rejects_nonexistent_word_id(self):
        words = [_sw("w-0001", "板", 0.0, 0.2)]
        candidates = [
            CorrectionCandidate(
                window_id="win-000", type="replace_display",
                word_ids=["w-9999"], from_text="x", to_text="y", confidence=0.90,
            )
        ]
        result = validate_display_patches(candidates, words)
        assert len(result.rejected) == 1

    def test_rejects_from_text_mismatch(self):
        words = [
            _sw("w-0001", "板", 0.0, 0.2),
            _sw("w-0002", "也", 0.2, 0.4),
        ]
        candidates = [
            CorrectionCandidate(
                window_id="win-000", type="replace_display",
                word_ids=["w-0002"], from_text="姐", to_text="也", confidence=0.90,
            )
        ]
        result = validate_display_patches(candidates, words)
        assert len(result.rejected) == 1

    def test_validates_replace_display_span(self):
        words = [
            _sw("w-0001", "定", 0.0, 0.2),
            _sw("w-0002", "性", 0.2, 0.4),
            _sw("w-0003", "晚", 0.4, 0.6),
        ]
        candidates = [
            CorrectionCandidate(
                window_id="win-000", type="replace_display_span",
                word_ids=["w-0001", "w-0002", "w-0003"],
                from_text="定性晚", to_text="定心丸", confidence=0.91,
            )
        ]
        result = validate_display_patches(candidates, words)
        assert len(result.accepted) == 1

    def test_rejects_empty_to_text_for_replace(self):
        words = [_sw("w-0001", "啊", 0.0, 0.2)]
        candidates = [
            CorrectionCandidate(
                window_id="win-000", type="replace_display",
                word_ids=["w-0001"], from_text="啊", to_text="", confidence=0.95,
            )
        ]
        result = validate_display_patches(candidates, words)
        assert len(result.rejected) == 1

    def test_validates_insert_display(self):
        words = [_sw("w-0001", "板", 0.0, 0.2), _sw("w-0002", "今", 0.2, 0.4)]
        candidates = [
            CorrectionCandidate(
                window_id="win-000", type="insert_display",
                after_word_id="w-0001", to_text="姐", confidence=0.87,
            )
        ]
        result = validate_display_patches(candidates, words)
        assert len(result.accepted) == 1

    def test_rejects_insert_with_empty_to_text(self):
        words = [_sw("w-0001", "板", 0.0, 0.2)]
        candidates = [
            CorrectionCandidate(
                window_id="win-000", type="insert_display",
                after_word_id="w-0001", to_text="", confidence=0.90,
            )
        ]
        result = validate_display_patches(candidates, words)
        assert len(result.rejected) == 1


class TestApplyDisplayPatches:
    def test_replace_display_changes_text(self):
        words = [
            _sw("w-0001", "板", 0.0, 0.2),
            _sw("w-0002", "也", 0.2, 0.4),
        ]
        patches = [
            DisplayPatch(
                patch_id="dp-001", type="replace_display",
                word_ids=["w-0002"], from_text="也", to_text="姐", confidence=0.93,
            )
        ]
        text = apply_display_patches(words, patches)
        assert text == "板姐"

    def test_replace_display_span(self):
        words = [
            _sw("w-0001", "定", 0.0, 0.2),
            _sw("w-0002", "性", 0.2, 0.4),
            _sw("w-0003", "晚", 0.4, 0.6),
        ]
        patches = [
            DisplayPatch(
                patch_id="dp-001", type="replace_display_span",
                word_ids=["w-0001", "w-0002", "w-0003"],
                from_text="定性晚", to_text="定心丸", confidence=0.91,
            )
        ]
        text = apply_display_patches(words, patches)
        assert text == "定心丸"

    def test_delete_display_noise(self):
        words = [
            _sw("w-0001", "嗯", 0.0, 0.2),
            _sw("w-0002", "好", 0.2, 0.4),
        ]
        patches = [
            DisplayPatch(
                patch_id="dp-001", type="delete_display_noise",
                word_ids=["w-0001"], from_text="嗯", confidence=0.90,
            )
        ]
        text = apply_display_patches(words, patches)
        assert text == "好"

    def test_no_patches_returns_original(self):
        words = [_sw("w-0001", "你", 0.0, 0.2), _sw("w-0002", "好", 0.2, 0.4)]
        text = apply_display_patches(words, [])
        assert text == "你好"
