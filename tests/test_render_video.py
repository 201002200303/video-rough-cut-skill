import shutil
import subprocess

import pytest

from schemas.models import Transcript, TranscriptSegment, VisualMetadata
from scripts.generate_subtitles import generate_subtitles
from scripts.generate_visual_overlay import generate_cover_ass
from scripts.generate_visual_overlay import generate_packaged_subtitles
from scripts.render_video import _compute_keep_ranges
from scripts.render_video import render_video


def test_render_uses_single_filter_complex_for_edit_ranges(tmp_path, monkeypatch):
    commands = []

    def fake_run(cmd, step):
        commands.append((step, cmd))

    monkeypatch.setattr("scripts.render_video._run_ffmpeg", fake_run)
    subtitles = tmp_path / "subtitles.ass"
    subtitles.write_text("[Script Info]\n\n[V4+ Styles]\n\n[Events]\n", encoding="utf-8")

    render_video(
        input_video_path=tmp_path / "input.mp4",
        edit_decisions=[{"type": "delete", "start": 0.5, "end": 0.8}],
        subtitles_path=subtitles,
        output_video_path=tmp_path / "out.mp4",
        visual_metadata={"enabled": False},
    )

    assert len(commands) == 1
    step, cmd = commands[0]
    assert step == "filter_complex cut/concat/subtitle"
    assert "-filter_complex" in cmd
    filter_text = cmd[cmd.index("-filter_complex") + 1]
    assert "trim=start=0:end=0.5" in filter_text
    assert "atrim=start=0.8" in filter_text
    assert "concat=n=2:v=1:a=1" in filter_text
    assert "ass='" in filter_text


def test_render_merges_tiny_keep_gap_between_pause_and_delete(tmp_path):
    keeps = _compute_keep_ranges(
        tmp_path / "input.mp4",
        [
            {"type": "compress_pause", "start": 44.71, "end": 45.05, "target_duration": 0.04},
            {"type": "delete", "start": 45.06, "end": 45.48},
        ],
    )

    assert keeps == [(0.0, 44.75), (45.48, None)]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_render_video_ffmpeg_smoke_with_cover(tmp_path):
    input_video = tmp_path / "input.mp4"
    base_ass = tmp_path / "subtitles.ass"
    overlay_ass = tmp_path / "visual_overlay.ass"
    cover_ass = tmp_path / "cover.ass"
    output_video = tmp_path / "out.mp4"
    cover_image = tmp_path / "cover.png"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=360x640:rate=25:duration=1.4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=1.4",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(input_video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    transcript = Transcript(
        language="zh",
        segments=[TranscriptSegment(id="s1", start=0.0, end=1.0, text="测试字幕", words=[])],
    )
    generate_subtitles(transcript, base_ass)
    metadata = VisualMetadata(
        cover_title="今天是\n反转信号？",
        date_label="2026.3.27",
        cover_subtitle="看盘笔记",
        top_right_label="0327 收评",
        person_intro="九方智投 投顾（谈军 登记编号：A0740625030028）",
        disclaimer_lines=[
            "历史数据/观点仅供参考 不构成投资建议",
            "不作为未来收益保证 据此操作风险自担",
            "投资有风险 入市需谨慎",
        ],
    )
    generate_packaged_subtitles(base_ass, metadata, overlay_ass)
    generate_cover_ass(metadata, cover_ass)

    render_video(
        input_video_path=input_video,
        edit_decisions=[{"type": "delete", "start": 0.4, "end": 0.7}],
        subtitles_path=overlay_ass,
        output_video_path=output_video,
        visual_metadata=metadata,
        cover_ass_path=cover_ass,
        cover_image_path=cover_image,
    )

    assert output_video.exists()
    assert output_video.stat().st_size > 0
    assert cover_image.exists()
    assert cover_image.stat().st_size > 0
