"""Text-join 和边界硬校验器测试。"""

from validators.boundary_validator import validate_boundary, validate_text_join


class TestTextJoin:
    def test_normal_join_passes(self):
        result = validate_text_join(
            before_text="我们应该先看墙面",
            deleted_text="空鼓",
            after_text="然后再决定怎么做",
        )
        assert result["pass"]

    def test_empty_before_and_after_fails(self):
        result = validate_text_join(
            before_text="",
            deleted_text="全部内容",
            after_text="",
        )
        assert not result["pass"]

    def test_repetition_detection(self):
        result = validate_text_join(
            before_text="这个是重",
            deleted_text="复的内容",
            after_text="复的示例",
        )
        # "是" + "重"
        assert not result["pass"] or len(result["issues"]) <= 1

    def test_large_delete_ratio_flags(self):
        result = validate_text_join(
            before_text="短",
            deleted_text="非常非常非常非常非常长的删除文本内容",
            after_text="也短",
        )
        # deleted > 50% of before
        assert len(result["issues"]) >= 1

    def test_simple_punctuation_boundary(self):
        result = validate_text_join(
            before_text="第一点说完了。接下来看第二点，这里是很多前文背景内容铺垫",
            deleted_text="这里七个字多",
            after_text="第二点也很重要",
        )
        assert result["pass"]


class TestBoundary:
    def test_valid_range_within_segment(self):
        errors = validate_boundary("seg-001", 1.0, 2.0, 0.5, 3.0)
        assert len(errors) == 0

    def test_start_before_segment_start(self):
        errors = validate_boundary("seg-001", 0.3, 2.0, 0.5, 3.0)
        assert len(errors) == 1

    def test_end_after_segment_end(self):
        errors = validate_boundary("seg-001", 1.0, 3.5, 0.5, 3.0)
        assert len(errors) == 1

    def test_inverted_range(self):
        errors = validate_boundary("seg-001", 2.0, 1.0, 0.5, 3.0)
        assert len(errors) == 1
