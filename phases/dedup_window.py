"""Phase 7: 窗口内去重/口误删除 — LLM + 硬校验 → DeletionCandidate。"""

from __future__ import annotations

import json
from pathlib import Path

from core.utils import load_config, setup_logger, ProviderError
from providers.aliyun_qwen import AliyunQwenProvider
from phases.build_windows import get_window_segments, get_window_words
from schemas.models import (
    DeletionCandidate,
    GlobalContext,
    SourceSegment,
    SourceWord,
    ValidatedDeletionFile,
    Window,
)
from validators.deletion_validator import validate_deletion_candidates

logger = setup_logger(__name__)


def dedup_window(
    window: Window,
    window_segments: list[SourceSegment],
    window_words: list[SourceWord],
    global_context: GlobalContext,
    dedup_prompt_path: Path,
    total_duration: float = 0.0,
) -> ValidatedDeletionFile:
    """对一个 window 执行 LLM 去重检测 + 硬校验。

    LLM 直接看原始 source text（不经纠错），删除候选必须绑定原始 source word_id。
    global_context.canonical_terms 帮助 LLM 理解全文不一致的 ASR 错字。
    """
    cfg = load_config().get("dedup", {})
    min_confidence = float(cfg.get("min_confidence", 0.88))

    template = dedup_prompt_path.read_text(encoding="utf-8")
    source_text = "".join(w.char for w in window_words)
    prompt = _build_dedup_prompt(window, window_segments, window_words, source_text, global_context, template)

    provider = AliyunQwenProvider()

    try:
        result = provider.dedup_window(prompt)
        candidates = _parse_dedup_response(result, window.window_id, min_confidence)
    except ProviderError:
        logger.warning("Window dedup LLM call failed for %s", window.window_id)
        return ValidatedDeletionFile()

    validated = validate_deletion_candidates(candidates, window_words, total_duration)
    return validated


def dedup_all_windows(
    windows: list[Window],
    source_segments: list[SourceSegment],
    source_words: list[SourceWord],
    global_context: GlobalContext,
    dedup_prompt_path: Path,
    output_path: Path | None = None,
) -> list[DeletionCandidate]:
    """对所有去重窗口执行去重，汇总所有 approved candidates。

    Args:
        windows: 去重窗口列表（phase="dedup"）。
        source_segments: 所有 source segments。
        source_words: 所有 source words。
        global_context: 全局语境（含 canonical_terms 供 LLM 理解不一致 ASR 错字）。
        dedup_prompt_path: 去重 prompt 模板路径。
        output_path: 可选的输出路径。

    Returns:
        所有通过硬校验的 DeletionCandidate 列表。
    """
    all_candidates: list[DeletionCandidate] = []
    all_rejected: list[dict] = []
    per_window_debug: list[dict] = []
    total_duration = sum((w.end - w.start) for w in source_words)

    for window in windows:
        ws = get_window_segments(window, source_segments)
        ww = get_window_words(window, source_words)

        validated = dedup_window(window, ws, ww, global_context, dedup_prompt_path, total_duration)
        all_candidates.extend(validated.accepted)
        all_rejected.extend(validated.rejected)
        per_window_debug.append({
            "window_id": window.window_id,
            "target_segments": window.target_segment_ids,
            "allowed_edit": window.allowed_edit_segment_ids,
            "accepted_count": len(validated.accepted),
            "rejected_count": len(validated.rejected),
            "rejected": validated.rejected,
        })

    logger.info("Total validated deletion candidates: %d across %d dedup windows", len(all_candidates), len(windows))

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps([c.model_dump() for c in all_candidates], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # 保存去重调试产物（每个窗口的 accepted + rejected 明细）
        debug_path = output_path.parent / f"{output_path.stem}_dedup_debug.json"
        debug_data = {
            "total_candidates": len(all_candidates),
            "total_rejected": len(all_rejected),
            "per_window": per_window_debug,
        }
        debug_path.write_text(
            json.dumps(debug_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Dedup debug saved: %s", debug_path)

    return all_candidates


def _build_dedup_prompt(
    window: Window,
    window_segments: list[SourceSegment],
    window_words: list[SourceWord],
    source_text: str,
    global_context: GlobalContext,
    template: str,
) -> str:
    segments_json = json.dumps(
        [
            {
                "segment_id": s.segment_id,
                "text": s.text,
                "editable": s.segment_id in window.allowed_edit_segment_ids,
            }
            for s in window_segments
        ],
        ensure_ascii=False,
    )
    words_json = json.dumps(
        [
            {"word_id": w.word_id, "char": w.char, "start": w.start, "end": w.end, "segment_id": w.segment_id}
            for w in window_words
        ],
        ensure_ascii=False,
    )
    prompt = template.replace("{{window_id}}", window.window_id)
    prompt = prompt.replace("{{segments_json}}", segments_json)
    prompt = prompt.replace("{{words_json}}", words_json)
    prompt = prompt.replace("{{source_text}}", source_text)
    prompt = prompt.replace("{{global_context}}", global_context.model_dump_json(indent=2))
    return prompt


def _parse_dedup_response(
    result: dict,
    window_id: str,
    min_confidence: float,
) -> list[DeletionCandidate]:
    candidates: list[DeletionCandidate] = []
    for i, item in enumerate(result.get("deletions", [])):
        c = DeletionCandidate(
            candidate_id=f"del-{window_id}-{i:03d}",
            window_id=window_id,
            type=item.get("type", "false_start"),
            word_ids=item.get("word_ids", []),
            delete_text_original=item.get("delete_text_original", ""),
            delete_text_corrected_view=item.get("delete_text_corrected_view", ""),
            before_text_corrected_view=item.get("before_text_corrected_view", ""),
            after_text_corrected_view=item.get("after_text_corrected_view", ""),
            reason=item.get("reason", ""),
            confidence=float(item.get("confidence", 0.0)),
        )
        if c.confidence >= min_confidence:
            candidates.append(c)
    return candidates

