"""V2.5 数据模型测试 — 校验规则、序列化、边界条件。"""

import json

import pytest
from pydantic import ValidationError as PydanticValidationError

from schemas.models import (
    CorrectionCandidate,
    CorrectedView,
    DeletionCandidate,
    DisplayPatch,
    GlobalContext,
    SegmentIssue,
    SegmentIssueFile,
    SourceSegment,
    SourceWord,
    ValidatedDeletionFile,
    ValidatedPatchFile,
    Window,
    WindowFile,
)


class TestSourceWord:
    def test_valid_provider_word(self):
        w = SourceWord(word_id="w-0001", char="你", start=0.0, end=0.2, segment_id="seg-001")
        assert w.word_id == "w-0001"
        assert w.timestamp_source == "provider"
        assert w.provider == "funasr"

    def test_source_word_negative_start_raises(self):
        with pytest.raises(PydanticValidationError):
            SourceWord(word_id="w-0001", char="你", start=-0.1, end=0.2, segment_id="seg-001")

    def test_source_word_invalid_timestamp_source_raises(self):
        with pytest.raises(PydanticValidationError):
            SourceWord(word_id="w-0001", char="你", start=0.0, end=0.2, segment_id="seg-001", timestamp_source="unknown")

    def test_source_word_end_before_start_raises(self):
        with pytest.raises(PydanticValidationError):
            SourceWord(word_id="w-0001", char="你", start=0.5, end=0.2, segment_id="seg-001")


class TestSourceSegment:
    def test_valid_segment(self):
        s = SourceSegment(segment_id="seg-001", text="你好", start=0.0, end=0.5, word_ids=["w-0001", "w-0002"])
        assert s.segment_id == "seg-001"
        assert s.split_reason == "pause_gap"

    def test_segment_negative_start_raises(self):
        with pytest.raises(PydanticValidationError):
            SourceSegment(segment_id="seg-001", text="你好", start=-0.1, end=0.5)


class TestDisplayPatch:
    def test_valid_replace_display(self):
        p = DisplayPatch(
            patch_id="dp-001",
            type="replace_display",
            word_ids=["w-0002"],
            from_text="也",
            to_text="姐",
            confidence=0.93,
            evidence={"category": "speaker_name_error"},
        )
        assert p.type == "replace_display"
        assert not p.affects_timeline

    def test_insert_display(self):
        p = DisplayPatch(
            patch_id="dp-002",
            type="insert_display",
            after_word_id="w-0005",
            to_text="姐",
            confidence=0.87,
        )
        assert p.type == "insert_display"
        assert p.after_word_id == "w-0005"

    def test_replace_display_span(self):
        p = DisplayPatch(
            patch_id="dp-003",
            type="replace_display_span",
            word_ids=["w-0003", "w-0004", "w-0005"],
            from_text="定性晚",
            to_text="定心丸",
            confidence=0.91,
        )
        assert p.type == "replace_display_span"

    def test_invalid_confidence_raises(self):
        with pytest.raises(PydanticValidationError):
            DisplayPatch(
                patch_id="dp-004",
                type="replace_display",
                word_ids=["w-0001"],
                from_text="x",
                to_text="y",
                confidence=1.5,
            )


class TestDeletionCandidate:
    def test_valid_false_start(self):
        dc = DeletionCandidate(
            candidate_id="del-001",
            window_id="win-000",
            type="false_start",
            word_ids=["w-0301", "w-0302", "w-0303", "w-0304"],
            delete_text_original="我觉得这个不是",
            reason="前半句是未完成表达",
            confidence=0.90,
        )
        assert dc.type == "false_start"
        assert dc.word_ids == ["w-0301", "w-0302", "w-0303", "w-0304"]

    def test_fast_repetition(self):
        dc = DeletionCandidate(
            candidate_id="del-002",
            window_id="win-000",
            type="fast_repetition",
            word_ids=["w-0410", "w-0411"],
            delete_text_original="这个这个",
            reason="快速机械重复",
            confidence=0.94,
        )
        assert dc.type == "fast_repetition"

    def test_invalid_confidence_raises(self):
        with pytest.raises(PydanticValidationError):
            DeletionCandidate(
                candidate_id="del-003",
                window_id="win-000",
                type="filler_phrase",
                word_ids=["w-0001"],
                delete_text_original="呃",
                reason="filler",
                confidence=-0.1,
            )


class TestGlobalContext:
    def test_default_global_context(self):
        ctx = GlobalContext()
        assert ctx.topic == ""
        assert ctx.speaker_aliases == []

    def test_global_context_with_data(self):
        ctx = GlobalContext(
            topic="财经复盘",
            speaker_aliases=["板姐"],
            confirmed_terms=["定心丸"],
            domain_terms=["K线", "均线"],
            possible_misrecognitions=[{"original": "板也", "suggested": "板姐", "confidence": 0.92}],
            uncertain_items=[{"item": "品牌名", "question": "是否有固定写法？"}],
        )
        assert ctx.topic == "财经复盘"
        assert len(ctx.speaker_aliases) == 1
        assert len(ctx.possible_misrecognitions) == 1

    def test_global_context_json_roundtrip(self):
        ctx = GlobalContext(
            topic="装修",
            speaker_aliases=["老王"],
            domain_terms=["阴阳角", "美缝"],
        )
        json_str = ctx.model_dump_json()
        restored = GlobalContext.model_validate_json(json_str)
        assert restored.topic == "装修"
        assert restored.speaker_aliases == ["老王"]


class TestSegmentIssue:
    def test_valid_issue(self):
        issue = SegmentIssue(
            segment_id="seg-012",
            issue_types=["speaker_name_error", "asr_homophone_error"],
            priority="high",
            evidence="'板也'应为'板姐'",
        )
        assert issue.priority == "high"
        assert len(issue.issue_types) == 2

    def test_defaults(self):
        issue = SegmentIssue(segment_id="seg-001")
        assert issue.issue_types == []
        assert issue.priority == "medium"

    def test_segment_issue_file(self):
        f = SegmentIssueFile(issues=[SegmentIssue(segment_id="seg-001", priority="low")])
        assert len(f.issues) == 1


class TestWindow:
    def test_window_construction(self):
        w = Window(
            window_id="win-000",
            target_segment_ids=["seg-003"],
            left_context_segment_ids=["seg-001", "seg-002"],
            right_context_segment_ids=["seg-004", "seg-005"],
            allowed_edit_segment_ids=["seg-003"],
        )
        assert w.window_id == "win-000"
        assert w.all_segment_ids == ["seg-001", "seg-002", "seg-003", "seg-004", "seg-005"]

    def test_window_merged_targets(self):
        w = Window(
            window_id="win-001",
            target_segment_ids=["seg-003", "seg-004", "seg-005"],
            left_context_segment_ids=["seg-001", "seg-002"],
            right_context_segment_ids=["seg-006", "seg-007"],
            allowed_edit_segment_ids=["seg-003", "seg-004", "seg-005"],
        )
        assert len(w.target_segment_ids) == 3
        assert len(w.all_segment_ids) == 7

    def test_window_file(self):
        w = Window(
            window_id="win-000",
            target_segment_ids=["seg-002"],
            allowed_edit_segment_ids=["seg-002"],
        )
        f = WindowFile(windows=[w])
        assert len(f.windows) == 1


class TestCorrectionCandidate:
    def test_valid_candidate(self):
        c = CorrectionCandidate(
            window_id="win-000",
            type="replace_display",
            word_ids=["w-0002"],
            from_text="也",
            to_text="姐",
            confidence=0.93,
            evidence={"category": "speaker_name_error"},
        )
        assert c.window_id == "win-000"
        assert c.type == "replace_display"


class TestCorrectedView:
    def test_corrected_view(self):
        cv = CorrectedView(
            window_id="win-000",
            source_text="我觉得这个不是，我们先看墙面",
            corrected_text="我觉得这个不是，我们先看墙面",
            applied_patch_ids=["dp-win-000-000"],
        )
        assert cv.window_id == "win-000"
        assert cv.source_text == cv.corrected_text

    def test_corrected_view_with_changes(self):
        cv = CorrectedView(
            window_id="win-001",
            source_text="板也今天认为",
            corrected_text="板姐今天认为",
            applied_patch_ids=["dp-win-001-000"],
            word_id_mapping={"w-0122": ["w-0122"]},
        )
        assert cv.source_text != cv.corrected_text


class TestValidatedFiles:
    def test_validated_patch_file(self):
        f = ValidatedPatchFile(
            accepted=[
                DisplayPatch(
                    patch_id="dp-001", type="replace_display",
                    word_ids=["w-0001"], from_text="也", to_text="姐", confidence=0.93
                )
            ],
            rejected=[{"error": "low confidence"}],
        )
        assert len(f.accepted) == 1
        assert len(f.rejected) == 1

    def test_validated_deletion_file(self):
        f = ValidatedDeletionFile(
            accepted=[
                DeletionCandidate(
                    candidate_id="del-001", window_id="win-000",
                    type="false_start", word_ids=["w-0001", "w-0002"],
                    delete_text_original="ab", reason="test", confidence=0.90
                )
            ],
            rejected=[],
        )
        assert len(f.accepted) == 1
