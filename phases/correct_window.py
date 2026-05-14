"""Phase 6: 窗口内 ASR 纠错 — LLM + 硬校验 → DisplayPatch。"""

from __future__ import annotations

import json
from pathlib import Path

from core.utils import load_config, setup_logger, ProviderError
from providers.aliyun_qwen import AliyunQwenProvider
from schemas.models import (
    CorrectionCandidate,
    DisplayPatch,
    GlobalContext,
    SourceSegment,
    SourceWord,
    ValidatedPatchFile,
    Window,
)
from validators.correction_validator import validate_display_patches
from phases.build_windows import get_window_segments, get_window_words

logger = setup_logger(__name__)


def correct_window(
    window: Window,
    window_segments: list[SourceSegment],
    window_words: list[SourceWord],
    global_context: GlobalContext,
    correct_prompt_path: Path,
    word_index_by_id: dict[str, int] | None = None,
) -> ValidatedPatchFile:
    """对一个 window 执行 LLM 纠错 + 硬校验。"""
    cfg = load_config().get("correction", {})
    if not bool(cfg.get("enabled", True)):
        return ValidatedPatchFile()

    min_confidence = float(cfg.get("min_confidence", 0.86))

    template = correct_prompt_path.read_text(encoding="utf-8")
    prompt = _build_correction_prompt(window, window_segments, window_words, global_context, template)

    provider = AliyunQwenProvider()

    try:
        result = provider.correct_window(prompt)
        candidates = _parse_correction_response(result, window.window_id, min_confidence)
    except ProviderError:
        logger.warning("Window correction LLM call failed for %s", window.window_id)
        return ValidatedPatchFile()

    return validate_display_patches(candidates, window_words, window.window_id)


def correct_all_windows(
    windows: list[Window],
    source_segments: list[SourceSegment],
    source_words: list[SourceWord],
    global_context: GlobalContext,
    correct_prompt_path: Path,
    output_path: Path | None = None,
) -> list[DisplayPatch]:
    """对所有 window 执行纠错，汇总所有 approved patches。"""
    all_patches: list[DisplayPatch] = []
    all_rejected: list[dict] = []

    word_index = {w.word_id: idx for idx, w in enumerate(source_words)}

    for window in windows:
        ws = get_window_segments(window, source_segments)
        ww = get_window_words(window, source_words)

        validated = correct_window(
            window,
            ws,
            ww,
            global_context,
            correct_prompt_path,
            word_index,
        )
        all_patches.extend(validated.accepted)
        all_rejected.extend(validated.rejected)

    logger.info("Total validated display patches: %d across %d windows", len(all_patches), len(windows))

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps([p.model_dump() for p in all_patches], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        debug_path = output_path.parent / f"{output_path.stem}_correction_debug.json"
        debug_path.write_text(
            json.dumps({
                "total_accepted": len(all_patches),
                "total_rejected": len(all_rejected),
                "rejected": all_rejected,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return all_patches


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


def _join_words(words: list[SourceWord]) -> str:
    return "".join(w.char for w in words)
