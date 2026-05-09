import json

from schemas.models import Transcript, TranscriptSegment, VisualMetadata
from scripts.generate_subtitles import generate_subtitles
from scripts.generate_visual_metadata import generate_visual_metadata
from scripts.generate_visual_metadata import load_visual_overrides
from scripts.generate_visual_overlay import generate_cover_ass
from scripts.generate_visual_overlay import generate_packaged_subtitles


def test_generate_visual_metadata_uses_overrides(tmp_path):
    transcript = Transcript(
        language="zh",
        segments=[TranscriptSegment(id="s1", start=0.0, end=1.0, text="家人们收盘了", words=[])],
    )
    out = tmp_path / "visual_metadata.json"

    metadata = generate_visual_metadata(
        transcript,
        out,
        {
            "cover_title": "今天是\\n反转信号？",
            "date_label": "2026.3.27",
            "top_right_label": "0327 收评",
            "insert_cover_seconds": 1.0,
        },
    )

    assert metadata.cover_title == "今天是\n反转信号？"
    assert metadata.date_label == "2026.3.27"
    assert metadata.top_right_label == "0327 收评"
    assert metadata.insert_cover_seconds == 1.0
    assert json.loads(out.read_text(encoding="utf-8"))["cover_title"] == "今天是\n反转信号？"


def test_load_visual_overrides_applies_cli_values_last(tmp_path):
    metadata_file = tmp_path / "visual.json"
    metadata_file.write_text(
        json.dumps({"cover_title": "旧标题", "date_label": "2026.3.26"}, ensure_ascii=False),
        encoding="utf-8",
    )

    overrides = load_visual_overrides(metadata_file, {"cover_title": "新标题", "person_intro": None})

    assert overrides["cover_title"] == "新标题"
    assert overrides["date_label"] == "2026.3.26"
    assert "person_intro" not in overrides


def test_generate_packaged_subtitles_fits_long_fixed_text(tmp_path):
    transcript = Transcript(
        language="zh",
        segments=[TranscriptSegment(id="s1", start=0.0, end=1.2, text="家人们收盘了", words=[])],
    )
    base_ass = tmp_path / "subtitles.ass"
    packaged_ass = tmp_path / "visual_overlay.ass"
    generate_subtitles(transcript, base_ass)
    metadata = VisualMetadata(
        cover_title="今天是\n反转信号？",
        date_label="2026.3.27",
        cover_subtitle="看盘笔记",
        top_right_label="0327 超长超长超长收评提醒",
        person_intro="九方智投 投顾（谈军 登记编号：A0740625030028）这是一段很长的人物介绍",
        disclaimer_lines=[
            "历史数据/观点仅供参考 不构成投资建议",
            "不作为未来收益保证 据此操作风险自担",
            "投资有风险 入市需谨慎",
        ],
    )

    generate_packaged_subtitles(base_ass, metadata, packaged_ass)
    text = packaged_ass.read_text(encoding="utf-8")

    assert "Style: Default" in text
    assert "Style: VisualTopRight" in text
    assert "Style: VisualBottomIntro" in text
    assert "Default,,0,0,0,,家人们收盘了" in text
    assert "{\\an9\\fs" in text
    assert "{\\an2\\fs" in text
    assert "..." in text
    assert "历史数据/观点仅供参考 不构成投资建议" in text


def test_generate_cover_ass_fits_title_and_left_bottom_labels(tmp_path):
    cover_ass = tmp_path / "cover.ass"
    metadata = VisualMetadata(
        cover_title="今天是不是重要反转信号？",
        date_label="2026.3.27",
        cover_subtitle="看盘笔记",
        top_right_label="0327 收评",
    )

    generate_cover_ass(metadata, cover_ass)
    text = cover_ass.read_text(encoding="utf-8")

    assert "Style: CoverTitle" in text
    assert "{\\an8\\fs" in text
    assert "今天是不是" in text
    assert "\\N" in text
    assert "{\\an7\\fs" in text
    assert "2026.3.27" in text
    assert "看盘笔记" in text
