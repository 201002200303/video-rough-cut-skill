"""从重映射转写数据生成 ASS 字幕文件。V2 + V2.5 兼容。"""

from __future__ import annotations

from pathlib import Path

from core.utils import load_config
from core.utils import setup_logger
from schemas.models import DisplayPatch, SourceWord, Transcript
from validators.correction_validator import apply_display_patches

logger = setup_logger(__name__)
def generate_subtitles(
    remapped_transcript: Transcript,
    output_path: Path,
    display_patches: list[DisplayPatch] | None = None,
) -> Path:
    """生成 ASS 字幕；所有视觉参数来自 config.default.yaml [subtitle]。

    V2.5: 可选 display_patches 用于纠错字幕文本，不影响时间轴。
    """
    cfg = load_config().get("subtitle", {})
    font_name: str = cfg.get("font_name", "Microsoft YaHei")
    font_size: int = int(cfg.get("font_size", 32))
    outline_width: int = int(cfg.get("outline_width", 2))
    primary_color: str = cfg.get("primary_color", "&H0000FFFF")
    outline_color: str = cfg.get("outline_color", "&H00000000")
    shadow_depth: int = int(cfg.get("shadow_depth", 1))
    margin_v: int = int(cfg.get("margin_v", 40))
    margin_l: int = int(cfg.get("margin_l", 30))
    margin_r: int = int(cfg.get("margin_r", 30))
    alignment: int = int(cfg.get("alignment", 2))
    max_chars_per_line: int = int(cfg.get("max_chars_per_line", 28))
    max_lines: int = int(cfg.get("max_lines", 2))
    play_res_x: int = int(cfg.get("play_res_x", 1920))
    play_res_y: int = int(cfg.get("play_res_y", 1080))

    # V2.5: 预计算 display patch 文本映射
    _patch_text_cache: dict[str, str] | None = None
    if display_patches:
        _patch_text_cache = _build_patch_text_map(display_patches, remapped_transcript)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,{font_name},{font_size},{primary_color},{primary_color},{outline_color},&H64000000,0,0,0,0,100,100,0,0,1,{outline_width},{shadow_depth},{alignment},{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = [header]
    for seg in remapped_transcript.segments:
        text = seg.text
        # V2.5: 应用 display patches
        if _patch_text_cache and seg.id in _patch_text_cache:
            text = _patch_text_cache[seg.id]
        text = _wrap_zh(text, max_chars_per_line, max_lines)
        lines.append(
            f"Dialogue: 0,{_ass_time(seg.start)},{_ass_time(seg.end)},Default,,0,0,0,,{text}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Subtitles generated: %s", output_path)
    return output_path


def _build_patch_text_map(
    patches: list[DisplayPatch],
    transcript: Transcript,
) -> dict[str, str]:
    """构建 segment_id -> patched text 映射。

    优先使用 TranscriptWord.word_id + apply_display_patches（与校验器一致，支持 insert_display）。
    无 word_id 的旧转写降级为按段内子串替换（insert 无法应用）。
    """
    result: dict[str, str] = {}

    for seg in transcript.segments:
        text = seg.text
        segment_word_ids = {w.word_id for w in seg.words if w.word_id}

        seg_patches: list[DisplayPatch] = []
        if segment_word_ids:
            for p in patches:
                if p.type == "insert_display":
                    if p.after_word_id and p.after_word_id in segment_word_ids:
                        seg_patches.append(p)
                elif p.word_ids and any(wid in segment_word_ids for wid in p.word_ids):
                    seg_patches.append(p)
        else:
            for p in patches:
                if p.type in ("replace_display", "replace_display_span") and p.from_text and p.from_text in text:
                    seg_patches.append(p)
                elif p.type == "delete_display_noise" and p.from_text and p.from_text in text:
                    seg_patches.append(p)

        if not seg_patches:
            result[seg.id] = text
            continue

        if segment_word_ids and seg.words and all(w.word_id for w in seg.words):
            pseudo_words = [
                SourceWord(
                    word_id=w.word_id,  # type: ignore[arg-type] — 已由 all() 保证
                    char=w.word,
                    start=w.start,
                    end=w.end,
                    segment_id=seg.id,
                    timestamp_source=w.timestamp_source,
                    provider="funasr",
                )
                for w in seg.words
            ]
            text = apply_display_patches(pseudo_words, seg_patches)
        else:
            # 旧产物：无 word_id，仅能做子串级 replace/delete；insert 跳过
            for patch in seg_patches:
                if patch.type == "insert_display":
                    continue
                if patch.type == "replace_display":
                    if patch.from_text and patch.from_text in text:
                        text = text.replace(patch.from_text, patch.to_text, 1)
                elif patch.type == "replace_display_span":
                    if patch.from_text and patch.from_text in text:
                        text = text.replace(patch.from_text, patch.to_text, 1)
                elif patch.type == "delete_display_noise":
                    if patch.from_text:
                        text = text.replace(patch.from_text, "", 1)

        result[seg.id] = text

    return result


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _wrap_zh(text: str, max_per_line: int, max_lines: int) -> str:
    text = text.strip()
    if len(text) <= max_per_line:
        return text
    first = text[:max_per_line]
    second = text[max_per_line : max_per_line * 2]
    if max_lines <= 1 or not second:
        return first
    return f"{first}\\N{second}"
