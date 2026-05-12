"""DisplayPatch 硬校验器 — 纯代码校验，不依赖 LLM。

校验每个纠错候选的 word_id 有效性、from_text 匹配、span 连续性、
置信度阈值、边界许可。替代 V2 中的 LLM review。
"""

from __future__ import annotations

from difflib import SequenceMatcher

from core.utils import load_config, setup_logger
from schemas.models import CorrectionCandidate, DisplayPatch, SourceWord, ValidatedPatchFile

logger = setup_logger(__name__)


def validate_display_patches(
    candidates: list[CorrectionCandidate],
    source_words: list[SourceWord],
    window_id: str = "",
) -> ValidatedPatchFile:
    """校验所有 correction candidates 并返回 accepted/rejected。"""
    cfg = load_config().get("validation", {})
    min_confidence = float(cfg.get("correction_min_confidence", 0.86))

    words_by_id = {w.word_id: w for w in source_words}

    accepted: list[DisplayPatch] = []
    rejected: list[dict] = []

    for i, c in enumerate(candidates):
        errors = _validate_one(c, words_by_id, min_confidence)
        if errors:
            rejected.append({"candidate_index": i, "candidate": c.model_dump(), "errors": errors})
            logger.warning("Correction candidate %d rejected: %s", i, errors)
        else:
            accepted.append(
                DisplayPatch(
                    patch_id=f"dp-{window_id}-{i:03d}" if window_id else f"dp-{i:03d}",
                    type=c.type,
                    word_ids=c.word_ids,
                    after_word_id=c.after_word_id,
                    from_text=c.from_text,
                    to_text=c.to_text,
                    confidence=c.confidence,
                    evidence=c.evidence,
                )
            )

    logger.info(
        "Correction validation: %d accepted, %d rejected (window=%s)",
        len(accepted),
        len(rejected),
        window_id or "N/A",
    )
    return ValidatedPatchFile(accepted=accepted, rejected=rejected)


def _validate_one(
    c: CorrectionCandidate,
    words_by_id: dict[str, SourceWord],
    min_confidence: float,
) -> list[str]:
    errors: list[str] = []

    if c.confidence < min_confidence:
        errors.append(f"confidence {c.confidence} < min {min_confidence}")

    if c.type in ("replace_display", "replace_display_span", "delete_display_noise"):
        if not c.word_ids:
            errors.append("word_ids must not be empty")
        else:
            errors.extend(_check_word_ids(c.word_ids, words_by_id))
            errors.extend(_check_from_text(c.from_text, c.word_ids, words_by_id))

    if c.type == "replace_display_span":
        if len(c.word_ids) < 2:
            errors.append("replace_display_span requires at least 2 word_ids")

    if c.type == "insert_display":
        if not c.to_text:
            errors.append("insert_display requires non-empty to_text")
        if c.after_word_id and c.after_word_id not in words_by_id:
            errors.append(f"after_word_id {c.after_word_id} not found in source words")
        if len(c.to_text) > 4:
            errors.append(f"insert_display text too long: {len(c.to_text)} > 4 chars")

    if c.type in ("replace_display", "replace_display_span"):
        if not c.to_text:
            errors.append("correction to_text must not be empty")
        if c.from_text and c.to_text:
            ratio = len(c.to_text) / max(len(c.from_text), 1)
            if ratio > 1.6 or ratio < 0.4:
                errors.append(f"length ratio {ratio:.2f} out of [0.4, 1.6]")
            # 单字符替换时跳过相似度检查 (如 "也" -> "姐")
            if len(c.from_text) > 1 or len(c.to_text) > 1:
                similarity = SequenceMatcher(None, c.from_text, c.to_text).ratio()
                if similarity < 0.3:
                    errors.append(f"text similarity {similarity:.2f} too low")

    return errors


def _check_word_ids(
    word_ids: list[str],
    words_by_id: dict[str, SourceWord],
) -> list[str]:
    errors: list[str] = []
    for wid in word_ids:
        if wid not in words_by_id:
            errors.append(f"word_id {wid} not found")
    if len(word_ids) >= 2:
        ordered_ids = sorted(word_ids, key=lambda x: int(x.split("-")[-1]))
        expected = list(range(int(ordered_ids[0].split("-")[-1]), int(ordered_ids[-1].split("-")[-1]) + 1))
        actual = [int(x.split("-")[-1]) for x in ordered_ids]
        if actual != expected:
            errors.append(f"word_ids not contiguous: {word_ids}")
    return errors


def _check_from_text(
    from_text: str,
    word_ids: list[str],
    words_by_id: dict[str, SourceWord],
) -> list[str]:
    errors: list[str] = []
    try:
        ordered = sorted(word_ids, key=lambda x: int(x.split("-")[-1]))
        expected = "".join(words_by_id[w].char for w in ordered)
        if from_text != expected:
            errors.append(f"from_text '{from_text}' != source '{expected}'")
    except (KeyError, ValueError):
        pass
    return errors


def apply_display_patches(
    words: list[SourceWord],
    patches: list[DisplayPatch],
) -> str:
    """将 approved display patches 应用到一组 source words，返回显示文本。"""
    chars = {w.word_id: w.char for w in words}
    ordered_ids = sorted(chars.keys(), key=lambda x: int(x.split("-")[-1]))

    # 应用 replace / delete
    for patch in patches:
        if patch.type == "replace_display" and patch.word_ids:
            wid = patch.word_ids[0]
            if wid in chars:
                chars[wid] = patch.to_text
        elif patch.type == "replace_display_span" and patch.word_ids:
            for wid in patch.word_ids:
                chars[wid] = ""
            if patch.word_ids:
                chars[patch.word_ids[0]] = patch.to_text
        elif patch.type == "delete_display_noise" and patch.word_ids:
            for wid in patch.word_ids:
                chars[wid] = ""

    # 应用 insert (按 after_word_id 排序)
    inserts = [p for p in patches if p.type == "insert_display"]
    inserts.sort(key=lambda p: int((p.after_word_id or "w-0000").split("-")[-1]))
    for patch in inserts:
        if patch.after_word_id and patch.after_word_id in chars:
            idx = ordered_ids.index(patch.after_word_id)
            insert_id = f"_ins_{patch.patch_id}"
            ordered_ids.insert(idx + 1, insert_id)
            chars[insert_id] = patch.to_text

    return "".join(chars.get(wid, "") for wid in ordered_ids)
