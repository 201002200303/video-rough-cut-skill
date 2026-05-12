"""Phase 6: 窗口内 ASR 纠错 — LLM + 硬校验 → DisplayPatch。"""

from __future__ import annotations

import json
from pathlib import Path

from core.utils import load_config, setup_logger, ProviderError
from providers.aliyun_qwen import AliyunQwenProvider
from schemas.models import (
    CorrectionCandidate,
    CorrectedView,
    DisplayPatch,
    GlobalContext,
    SourceSegment,
    SourceWord,
    ValidatedPatchFile,
    Window,
)
from validators.correction_validator import apply_display_patches, validate_display_patches

logger = setup_logger(__name__)


def correct_window(
    window: Window,
    window_segments: list[SourceSegment],
    window_words: list[SourceWord],
    global_context: GlobalContext,
    correct_prompt_path: Path,
    word_index_by_id: dict[str, int] | None = None,
) -> tuple[ValidatedPatchFile, CorrectedView]:
    """对一个 window 执行 LLM 纠错 + 硬校验。

    Returns:
        (validated_patches, corrected_view) — patches 是最终字幕补丁，
        corrected_view 是临时视图供 dedup 阶段使用。
    """
    cfg = load_config().get("correction", {})
    if not bool(cfg.get("enabled", True)):
        empty = ValidatedPatchFile()
        cv = CorrectedView(
            window_id=window.window_id,
            source_text=_join_words(window_words),
            corrected_text=_join_words(window_words),
        )
        return empty, cv

    min_confidence = float(cfg.get("min_confidence", 0.86))

    # 构建 prompt
    template = correct_prompt_path.read_text(encoding="utf-8")
    prompt = _build_correction_prompt(window, window_segments, window_words, global_context, template)

    provider = AliyunQwenProvider()

    try:
        result = provider.correct_window(prompt)
        candidates = _parse_correction_response(result, window.window_id, min_confidence)
    except ProviderError:
        logger.warning("Window correction LLM call failed for %s", window.window_id)
        empty = ValidatedPatchFile()
        cv = CorrectedView(
            window_id=window.window_id,
            source_text=_join_words(window_words),
            corrected_text=_join_words(window_words),
        )
        return empty, cv

    # 硬校验
    validated = validate_display_patches(candidates, window_words, window.window_id)

    # 构建 corrected_view
    source_text = _join_words(window_words)
    corrected_text = apply_display_patches(window_words, validated.accepted)
    cv = CorrectedView(
        window_id=window.window_id,
        source_text=source_text,
        corrected_text=corrected_text,
        applied_patch_ids=[p.patch_id for p in validated.accepted],
    )

    return validated, cv


def correct_all_windows(
    windows: list[Window],
    source_segments: list[SourceSegment],
    source_words: list[SourceWord],
    global_context: GlobalContext,
    correct_prompt_path: Path,
    output_path: Path | None = None,
) -> tuple[list[DisplayPatch], dict[str, CorrectedView]]:
    """对所有 window 执行纠错，汇总所有 approved patches 和 corrected views。

    Returns:
        (all_patches, views_by_window_id) — patches 是跨所有窗口的最终字幕补丁，
        views 供 dedup 阶段使用。
    """
    all_patches: list[DisplayPatch] = []
    views: dict[str, CorrectedView] = {}

    seg_index = {s.segment_id: idx for idx, s in enumerate(source_segments)}
    word_index = {w.word_id: idx for idx, w in enumerate(source_words)}

    for window in windows:
        ws = _get_window_segments(window, source_segments)
        ww = _get_window_words(window, source_words, source_segments)

        _, cv = correct_window(
            window,
            ws,
            ww,
            global_context,
            correct_prompt_path,
            word_index,
        )
        views[window.window_id] = cv

        # Re-run with parsed candidates to get patches
        # (In practice this would be one pass — the correct_window function handles it)
        # Here we accumulate from a full run
        cfg = load_config().get("correction", {})
        if not bool(cfg.get("enabled", True)):
            continue

        template = correct_prompt_path.read_text(encoding="utf-8")
        prompt = _build_correction_prompt(window, ws, ww, global_context, template)
        provider = AliyunQwenProvider()
        try:
            result = provider.correct_window(prompt)
            candidates = _parse_correction_response(result, window.window_id, float(cfg.get("min_confidence", 0.86)))
            validated = validate_display_patches(candidates, ww, window.window_id)
            all_patches.extend(validated.accepted)
        except ProviderError:
            logger.warning("Window correction failed for %s", window.window_id)

    logger.info("Total validated display patches: %d across %d windows", len(all_patches), len(windows))

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps([p.model_dump() for p in all_patches], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return all_patches, views


def _build_correction_prompt(
    window: Window,
    window_segments: list[SourceSegment],
    window_words: list[SourceWord],
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
        [{"word_id": w.word_id, "char": w.char, "start": w.start, "end": w.end, "segment_id": w.segment_id} for w in window_words],
        ensure_ascii=False,
    )
    prompt = template.replace("{{window_id}}", window.window_id)
    prompt = prompt.replace("{{segments_json}}", segments_json)
    prompt = prompt.replace("{{words_json}}", words_json)
    prompt = prompt.replace("{{global_context}}", global_context.model_dump_json(indent=2))
    return prompt


def _parse_correction_response(
    result: dict,
    window_id: str,
    min_confidence: float,
) -> list[CorrectionCandidate]:
    candidates: list[CorrectionCandidate] = []
    for item in result.get("corrections", []):
        c = CorrectionCandidate(
            window_id=window_id,
            type=item.get("type", "replace_display"),
            word_ids=item.get("word_ids", []),
            after_word_id=item.get("after_word_id"),
            from_text=item.get("from_text", ""),
            to_text=item.get("to_text", ""),
            confidence=float(item.get("confidence", 0.0)),
            evidence=item.get("evidence", {}),
        )
        if c.confidence >= min_confidence:
            candidates.append(c)
    return candidates


def _get_window_segments(
    window: Window,
    source_segments: list[SourceSegment],
) -> list[SourceSegment]:
    seg_by_id = {s.segment_id: s for s in source_segments}
    result: list[SourceSegment] = []
    for sid in window.all_segment_ids:
        if sid in seg_by_id:
            result.append(seg_by_id[sid])
    return result


def _get_window_words(
    window: Window,
    source_words: list[SourceWord],
    source_segments: list[SourceSegment],
) -> list[SourceWord]:
    """获取 window 内所有 segment 的 source words。"""
    seg_ids = set(window.all_segment_ids)
    return [w for w in source_words if w.segment_id in seg_ids]


def _join_words(words: list[SourceWord]) -> str:
    return "".join(w.char for w in words)
