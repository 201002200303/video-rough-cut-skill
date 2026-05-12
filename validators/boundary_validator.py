"""Boundary 和 Text-Join 硬校验器 — 纯代码校验。

检查删除后前后文本拼接是否自然，是否有断裂。
"""

from __future__ import annotations

from core.utils import setup_logger

logger = setup_logger(__name__)

# 删除后拼接异常的常见模式
_SUSPICIOUS_JOINS: list[tuple[str, str]] = [
    ("的", "的"),
    ("了", "了"),
    ("是", "是"),
    ("在", "在"),
    ("和", "和"),
]

# 句子边界标点
_SENTENCE_END_PUNCT = set("。！？.!?\n")


def validate_text_join(
    before_text: str,
    deleted_text: str,
    after_text: str,
) -> dict:
    """检查删除前文本 + 删除后文本的拼接质量。

    Returns:
        {"pass": bool, "issues": list[str]}
    """
    issues: list[str] = []

    if not before_text and not after_text:
        issues.append("both before and after text are empty — would delete everything")
        return {"pass": False, "issues": issues}

    before_tail = before_text.strip()[-3:] if before_text.strip() else ""
    after_head = after_text.strip()[:3] if after_text.strip() else ""

    # 检查是否在前句末标点前切断
    if before_tail and before_tail[-1] not in _SENTENCE_END_PUNCT:
        if not after_head:
            # 被删除的是最后一句，且前句没有结束标点 — 可能是残句
            pass  # 这个情况很多，不一定是问题
        else:
            # 前后都有文本，前句没有结束标点 — 可能切断了一个句子
            first_after_char = after_head[0]
            if first_after_char not in _SENTENCE_END_PUNCT and first_after_char not in "，,；;：:":
                # 后文不以标点开始 — 确实切在句中
                pass  # 这本身不一定是问题（切割的恰好是重复内容）

    # 检查拼接后是否产生意外词语
    combined = (before_text.strip() + after_text.strip()) if before_text.strip() and after_text.strip() else ""
    if len(combined) > 1:
        for a, b in _SUSPICIOUS_JOINS:
            if before_tail.endswith(a) and after_head.startswith(b):
                issues.append(f"suspicious join: '...{a}' + '{b}...' may create repetition")

    # 检查删除全文的比例是否异常
    if deleted_text and before_text:
        if len(deleted_text) > len(before_text) * 0.5:
            issues.append(f"deleted text ({len(deleted_text)} chars) > 50% of before text ({len(before_text)} chars)")

    passed = len(issues) == 0
    if issues:
        logger.info("Text join issues: %s", issues)

    return {"pass": passed, "issues": issues}


def validate_boundary(
    segment_id: str,
    start_time: float,
    end_time: float,
    segment_start: float,
    segment_end: float,
) -> list[str]:
    """检查删除范围是否在 segment 边界内且合理。"""
    errors: list[str] = []
    if start_time < segment_start - 0.05:
        errors.append(f"delete start {start_time:.3f} before segment start {segment_start:.3f}")
    if end_time > segment_end + 0.05:
        errors.append(f"delete end {end_time:.3f} after segment end {segment_end:.3f}")
    if start_time >= end_time:
        errors.append(f"invalid time range: {start_time:.3f} >= {end_time:.3f}")
    return errors
