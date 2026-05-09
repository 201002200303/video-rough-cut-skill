"""Generate ASS overlay files for cover art and fixed video packaging text."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.utils import load_config
from core.utils import setup_logger
from schemas.models import VisualMetadata

logger = setup_logger(__name__)


def generate_packaged_subtitles(
    base_subtitles_path: Path,
    metadata: VisualMetadata,
    output_path: Path,
) -> Path:
    """Append top-right and bottom fixed overlay events to an existing ASS file."""
    text = base_subtitles_path.read_text(encoding="utf-8")
    if not metadata.enabled:
        output_path.write_text(text, encoding="utf-8")
        return output_path

    cfg = load_config()
    play_res_x = int(cfg.get("subtitle", {}).get("play_res_x", 1080))
    play_res_y = int(cfg.get("subtitle", {}).get("play_res_y", 1920))
    overlay_cfg = cfg.get("visual_overlay", {})
    layout = overlay_cfg.get("layout", {})
    colors = overlay_cfg.get("colors", {})
    font_name = cfg.get("subtitle", {}).get("font_name", "Microsoft YaHei")

    style_block = _video_overlay_styles(font_name, colors, layout)
    event_lines = _video_overlay_events(metadata, play_res_x, play_res_y, layout)
    packaged = _insert_styles(text, style_block)
    packaged = packaged.rstrip() + "\n" + "\n".join(event_lines) + "\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(packaged, encoding="utf-8")
    logger.info("Visual overlay subtitles generated: %s", output_path)
    return output_path


def generate_cover_ass(metadata: VisualMetadata, output_path: Path) -> Path:
    """Generate ASS text used to burn the large cover title onto a still frame."""
    cfg = load_config()
    subtitle_cfg = cfg.get("subtitle", {})
    overlay_cfg = cfg.get("visual_overlay", {})
    layout = overlay_cfg.get("layout", {})
    colors = overlay_cfg.get("colors", {})
    play_res_x = int(subtitle_cfg.get("play_res_x", 1080))
    play_res_y = int(subtitle_cfg.get("play_res_y", 1920))
    font_name = subtitle_cfg.get("font_name", "Microsoft YaHei")

    title_size = int(layout.get("cover_title_font_size", 158))
    date_size = int(layout.get("cover_date_font_size", 70))
    yellow = colors.get("yellow", "&H0000FFFF")
    black = colors.get("black", "&H00000000")
    soft_black = colors.get("soft_black", "&H7A000000")

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        f"Style: CoverTitle,{font_name},{title_size},{yellow},{yellow},{black},{soft_black},1,0,0,0,100,100,0,0,1,8,3,8,20,20,20,1",
        f"Style: CoverDate,{font_name},{date_size},{yellow},{yellow},{black},{soft_black},1,0,0,0,100,100,0,0,1,5,2,7,20,20,20,1",
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    end_time = _ass_time(10.0)
    fitted_title = _fit_text(
        metadata.cover_title,
        base_font_size=title_size,
        min_font_size=int(layout.get("cover_title_min_font_size", 104)),
        box_width=int(layout.get("cover_title_box_width", 900)),
        max_chars_per_line=int(layout.get("cover_title_max_chars_per_line", 7)),
        max_lines=int(layout.get("cover_title_max_lines", 2)),
    )
    lines.append(
        "Dialogue: 10,0:00:00.00,"
        f"{end_time},CoverTitle,,0,0,0,,{{\\an8\\fs{fitted_title.font_size}\\pos({play_res_x // 2},{int(layout.get('cover_title_y', 300))})}}{fitted_title.ass_text}"
    )
    if metadata.date_label:
        fitted_date = _fit_text(
            metadata.date_label,
            base_font_size=date_size,
            min_font_size=int(layout.get("cover_date_min_font_size", 48)),
            box_width=int(layout.get("cover_date_box_width", 520)),
            max_chars_per_line=12,
            max_lines=1,
        )
        lines.append(
            "Dialogue: 10,0:00:00.00,"
            f"{end_time},CoverDate,,0,0,0,,{{\\an7\\fs{fitted_date.font_size}\\pos({int(layout.get('cover_date_x', 120))},{int(layout.get('cover_date_y', 1460))})}}{fitted_date.ass_text}"
        )
    if metadata.cover_subtitle:
        fitted_subtitle = _fit_text(
            metadata.cover_subtitle,
            base_font_size=date_size,
            min_font_size=int(layout.get("cover_date_min_font_size", 48)),
            box_width=int(layout.get("cover_date_box_width", 520)),
            max_chars_per_line=8,
            max_lines=1,
        )
        lines.append(
            "Dialogue: 10,0:00:00.00,"
            f"{end_time},CoverDate,,0,0,0,,{{\\an7\\fs{fitted_subtitle.font_size}\\pos({int(layout.get('cover_date_x', 120))},{int(layout.get('cover_subtitle_y', 1545))})}}{fitted_subtitle.ass_text}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Cover ASS generated: %s", output_path)
    return output_path


def _video_overlay_styles(font_name: str, colors: dict[str, str], layout: dict[str, Any]) -> str:
    yellow = colors.get("yellow", "&H0000FFFF")
    white = colors.get("white", "&H00FFFFFF")
    black = colors.get("black", "&H00000000")
    soft_black = colors.get("soft_black", "&H7A000000")
    top_size = int(layout.get("top_right_font_size", 58))
    intro_size = int(layout.get("bottom_intro_font_size", 36))
    disclaimer_size = int(layout.get("bottom_disclaimer_font_size", 34))
    return "\n".join(
        [
            f"Style: VisualTopRight,{font_name},{top_size},{yellow},{yellow},{black},{soft_black},1,0,0,0,100,100,0,0,1,5,2,9,20,20,20,1",
            f"Style: VisualBottomIntro,{font_name},{intro_size},{white},{white},{black},{soft_black},1,0,0,0,100,100,0,0,1,3,1,2,20,20,20,1",
            f"Style: VisualBottomDisclaimer,{font_name},{disclaimer_size},{white},{white},{black},{soft_black},1,0,0,0,100,100,0,0,1,3,1,2,20,20,20,1",
        ]
    )


def _video_overlay_events(
    metadata: VisualMetadata,
    play_res_x: int,
    play_res_y: int,
    layout: dict[str, Any],
) -> list[str]:
    start = _ass_time(0.0)
    end = _ass_time(35999.0)
    events: list[str] = []
    if metadata.top_right_label:
        fitted_label = _fit_text(
            metadata.top_right_label,
            base_font_size=int(layout.get("top_right_font_size", 58)),
            min_font_size=int(layout.get("top_right_min_font_size", 36)),
            box_width=int(layout.get("top_right_box_width", 460)),
            max_chars_per_line=10,
            max_lines=1,
        )
        events.append(
            f"Dialogue: 5,{start},{end},VisualTopRight,,0,0,0,,"
            f"{{\\an9\\fs{fitted_label.font_size}\\pos({int(layout.get('top_right_x', play_res_x - 70))},{int(layout.get('top_right_y', 92))})}}"
            f"{fitted_label.ass_text}"
        )
    if metadata.person_intro:
        fitted_intro = _fit_text(
            metadata.person_intro,
            base_font_size=int(layout.get("bottom_intro_font_size", 36)),
            min_font_size=int(layout.get("bottom_intro_min_font_size", 26)),
            box_width=int(layout.get("bottom_intro_box_width", play_res_x - 120)),
            max_chars_per_line=32,
            max_lines=int(layout.get("bottom_intro_max_lines", 1)),
        )
        events.append(
            f"Dialogue: 5,{start},{end},VisualBottomIntro,,0,0,0,,"
            f"{{\\an2\\fs{fitted_intro.font_size}\\pos({play_res_x // 2},{int(layout.get('bottom_intro_y', play_res_y - 205))})}}"
            f"{fitted_intro.ass_text}"
        )
    first_y = int(layout.get("bottom_disclaimer_first_y", play_res_y - 140))
    gap = int(layout.get("bottom_disclaimer_line_gap", 43))
    for index, line in enumerate(metadata.disclaimer_lines[:3]):
        fitted_disclaimer = _fit_text(
            line,
            base_font_size=int(layout.get("bottom_disclaimer_font_size", 34)),
            min_font_size=int(layout.get("bottom_disclaimer_min_font_size", 24)),
            box_width=int(layout.get("bottom_disclaimer_box_width", play_res_x - 100)),
            max_chars_per_line=34,
            max_lines=int(layout.get("bottom_disclaimer_max_lines", 1)),
        )
        events.append(
            f"Dialogue: 5,{start},{end},VisualBottomDisclaimer,,0,0,0,,"
            f"{{\\an2\\fs{fitted_disclaimer.font_size}\\pos({play_res_x // 2},{first_y + index * gap})}}{fitted_disclaimer.ass_text}"
        )
    return events


def _insert_styles(ass_text: str, style_block: str) -> str:
    if "Style: VisualTopRight" in ass_text:
        return ass_text
    marker = "\n[Events]"
    if marker not in ass_text:
        raise ValueError("ASS file missing [Events] section")
    before, after = ass_text.split(marker, 1)
    return before.rstrip() + "\n" + style_block + marker + after


def _ass_text(text: str) -> str:
    return text.replace("{", "").replace("}", "").replace("\\N", "\n").strip()


class _FittedText:
    def __init__(self, font_size: int, lines: list[str]) -> None:
        self.font_size = font_size
        self.lines = lines

    @property
    def ass_text(self) -> str:
        return "\\N".join(_ass_text(line).replace("\n", "") for line in self.lines)


def _fit_text(
    text: str,
    base_font_size: int,
    min_font_size: int,
    box_width: int,
    max_chars_per_line: int,
    max_lines: int,
) -> _FittedText:
    cleaned = _ass_text(text).replace("\\n", "\n")
    for font_size in range(base_font_size, min_font_size - 1, -2):
        max_units = max(1, min(max_chars_per_line, int(box_width / max(1.0, font_size * 0.56))))
        lines = _wrap_display_units(cleaned, max_units=max_units, max_lines=max_lines)
        if lines and all(_estimated_text_width(line, font_size) <= box_width for line in lines):
            return _FittedText(font_size, lines)
    max_units = max(1, int(box_width / max(1.0, min_font_size * 0.56)))
    lines = _wrap_display_units(cleaned, max_units=max_units, max_lines=max_lines)
    return _FittedText(min_font_size, [_truncate_to_width(line, min_font_size, box_width) for line in lines])


def _wrap_display_units(text: str, max_units: int, max_lines: int) -> list[str]:
    paragraphs = [part.strip() for part in text.splitlines() if part.strip()]
    if not paragraphs:
        return []
    lines: list[str] = []
    for paragraph in paragraphs:
        current = ""
        current_units = 0.0
        for char in paragraph:
            unit = _char_units(char)
            if current and current_units + unit > max_units:
                lines.append(current)
                current = char
                current_units = unit
            else:
                current += char
                current_units += unit
        if current:
            lines.append(current)
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    overflow = "".join(lines[max_lines:])
    kept[-1] = kept[-1] + overflow
    return kept


def _estimated_text_width(text: str, font_size: int) -> float:
    return sum(_char_units(char) for char in text) * font_size * 0.56


def _char_units(char: str) -> float:
    if "\u4e00" <= char <= "\u9fff":
        return 1.85
    if char.isspace():
        return 0.55
    if char.isascii():
        return 0.95
    return 1.55


def _truncate_to_width(text: str, font_size: int, box_width: int) -> str:
    if _estimated_text_width(text, font_size) <= box_width:
        return text
    suffix = "..."
    out = ""
    for char in text:
        candidate = out + char + suffix
        if _estimated_text_width(candidate, font_size) > box_width:
            break
        out += char
    return (out or text[:1]) + suffix


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
