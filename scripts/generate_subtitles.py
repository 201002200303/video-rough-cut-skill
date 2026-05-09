"""从重映射转写数据生成 ASS 字幕文件。"""

from pathlib import Path

from core.utils import load_config
from core.utils import setup_logger
from schemas.models import Transcript

logger = setup_logger(__name__)


def generate_subtitles(
    remapped_transcript: Transcript,
    output_path: Path,
) -> Path:
    """生成 ASS 字幕；所有视觉参数来自 config.default.yaml [subtitle]。"""
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
        text = _wrap_zh(seg.text, max_chars_per_line, max_lines)
        lines.append(
            f"Dialogue: 0,{_ass_time(seg.start)},{_ass_time(seg.end)},Default,,0,0,0,,{text}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Subtitles generated: %s", output_path)
    return output_path


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
