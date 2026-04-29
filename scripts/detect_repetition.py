"""基于 LLM 的语义重复检测。"""

import json
from pathlib import Path

from core.config import load_config
from core.logging import setup_logger
from providers.aliyun_qwen import AliyunQwenProvider
from schemas.edit_decision import EditDecision

logger = setup_logger(__name__)


def detect_repetition(
    semantic_segments: list[dict],
    prompt_template_path: Path,
    semantic_window_seconds: float | None = None,
    min_confidence_to_delete: float | None = None,
    context_window_segments: int | None = None,
    max_segment_chars: int | None = None,
    review_on_uncertain: bool | None = None,
    max_auto_delete_duration: float | None = None,
) -> tuple[list[EditDecision], list[dict]]:
    """检测近邻语义重复片段并生成删除编辑决策。"""
    cfg = load_config().get("dedup", {})
    semantic_window_seconds = float(
        semantic_window_seconds if semantic_window_seconds is not None else cfg.get("semantic_window_seconds", 90.0)
    )
    min_confidence_to_delete = float(
        min_confidence_to_delete if min_confidence_to_delete is not None else cfg.get("similarity_threshold", 0.85)
    )
    context_window_segments = int(
        context_window_segments if context_window_segments is not None else cfg.get("context_window_segments", 3)
    )
    max_segment_chars = int(max_segment_chars if max_segment_chars is not None else cfg.get("max_segment_chars", 500))
    review_on_uncertain = bool(
        review_on_uncertain if review_on_uncertain is not None else cfg.get("review_on_uncertain", True)
    )
    max_auto_delete_duration = float(
        max_auto_delete_duration
        if max_auto_delete_duration is not None
        else cfg.get("max_auto_delete_duration", 4.0)
    )
    provider = AliyunQwenProvider()
    review_needed: list[dict] = []
    edits: list[EditDecision] = []
    emitted_delete_ids: set[str] = set()
    # 建立 segment_id -> 原始 segment 的映射，用于 review_needed 可读信息
    seg_by_id: dict[str, dict] = {s["segment_id"]: s for s in semantic_segments}
    prompt_template = prompt_template_path.read_text(encoding="utf-8")

    for i, seg in enumerate(semantic_segments):
        window = []
        start_idx = max(0, i - context_window_segments)
        for cand in semantic_segments[start_idx : i + 1]:
            if seg["start"] - cand["start"] <= semantic_window_seconds:
                window.append(_trim_segment_text(cand, max_segment_chars))
        if len(window) <= 1:
            continue
        prompt = _build_prompt(prompt_template, window)
        result = provider.semantic_dedup(prompt)
        for item in result.get("duplicate_groups", []):
            keep_id = item.get("keep_segment_id")
            delete_ids = item.get("delete_segment_ids", [])
            reason = item.get("reason", "semantic_dedup")
            conf = float(item.get("confidence", 0.0))
            for d_id in delete_ids:
                if d_id in emitted_delete_ids:
                    continue
                target = next((x for x in window if x["segment_id"] == d_id), None)
                if not target:
                    continue
                duration = float(target["end"]) - float(target["start"])
                if duration > max_auto_delete_duration:
                    review_needed.append(
                        {
                            "type": "duplicate_delete_too_long",
                            "segment_id": d_id,
                            "segment_text_preview": str(seg_by_id.get(d_id, {}).get("text", ""))[:80],
                            "keep_segment_id": keep_id,
                            "keep_text_preview": str(seg_by_id.get(keep_id, {}).get("text", ""))[:80],
                            "start": target["start"],
                            "end": target["end"],
                            "duration": duration,
                            "confidence": conf,
                            "reason": reason,
                        }
                    )
                    continue
                if conf >= min_confidence_to_delete:
                    emitted_delete_ids.add(d_id)
                    edits.append(
                        EditDecision(
                            type="delete",
                            start=target["start"],
                            end=target["end"],
                            reason=reason,
                            source="semantic_dedup",
                            confidence=conf,
                        )
                    )
                elif review_on_uncertain:
                    del_seg = seg_by_id.get(d_id, {})
                    keep_seg = seg_by_id.get(keep_id, {})
                    review_needed.append(
                        {
                            "type": "duplicate_low_confidence",
                            "segment_id": d_id,
                            "segment_text_preview": str(del_seg.get("text", ""))[:80],
                            "keep_segment_id": keep_id,
                            "keep_text_preview": str(keep_seg.get("text", ""))[:80],
                            "confidence": conf,
                            "reason": reason,
                        }
                    )
        review_needed.extend(_normalize_review_needed(result.get("review_needed", []), seg_by_id))
    logger.info("Semantic dedup edits=%d review_needed=%d", len(edits), len(review_needed))
    return edits, review_needed


def _build_prompt(template: str, window: list[dict]) -> str:
    payload = {"segments": window}
    return f"{template}\n\n输入:\n{json.dumps(payload, ensure_ascii=False)}"


def _trim_segment_text(segment: dict, max_chars: int) -> dict:
    trimmed = dict(segment)
    text = str(trimmed.get("text", ""))
    if len(text) > max_chars:
        trimmed["text"] = text[:max_chars]
    return trimmed


def _normalize_review_needed(items: list, seg_by_id: dict | None = None) -> list[dict]:
    """将 provider 返回的 review_needed 数据规范化为 list[dict]。"""
    normalized: list[dict] = []
    seg_by_id = seg_by_id or {}
    for item in items or []:
        if isinstance(item, dict):
            # 补充文本预览信息
            seg_id = item.get("segment_id", "")
            if seg_id and "segment_text_preview" not in item:
                seg = seg_by_id.get(seg_id, {})
                item["segment_text_preview"] = str(seg.get("text", ""))[:80]
            normalized.append(item)
            continue
        # 纯字符串类型的 review item，尝试提取 segment_id
        item_str = str(item)
        seg_id = item_str if item_str.startswith("s_") else ""
        preview = ""
        if seg_id:
            seg = seg_by_id.get(seg_id, {})
            preview = str(seg.get("text", ""))[:80]
        normalized.append(
            {
                "type": "provider_review_item",
                "detail": item_str,
                "segment_id": seg_id,
                "segment_text_preview": preview,
            }
        )
    return normalized