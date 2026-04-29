"""使用 FFmpeg 渲染带字幕的编辑视频。"""

import subprocess
from pathlib import Path

from core.config import load_config
from core.exceptions import ExternalCommandError
from core.logging import setup_logger

logger = setup_logger(__name__)


def render_video(
    input_video_path: Path,
    edit_decisions: list[dict],
    subtitles_path: Path,
    output_video_path: Path,
) -> Path:
    """根据编辑决策和字幕渲染最终视频。"""
    render_cfg = load_config().get("render", {})
    output_video_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_video_path.parent / "tmp_render"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    keep_ranges = _compute_keep_ranges(input_video_path, edit_decisions)
    if not keep_ranges:
        keep_ranges = [(0.0, None)]
    if len(keep_ranges) == 1 and keep_ranges[0][0] == 0.0 and keep_ranges[0][1] is None:
        return _burn_subtitles(input_video_path, subtitles_path, output_video_path)

    segment_files = []
    for idx, (start, end) in enumerate(keep_ranges):
        seg_file = tmp_dir / f"seg_{idx:03d}.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(input_video_path),
            "-copyts",
        ]
        if end is not None:
            cmd += ["-to", str(end)]
        cmd += _encode_args(render_cfg) + [str(seg_file)]
        _run_ffmpeg(cmd, "segment cut")
        segment_files.append(seg_file)
    concat_txt = tmp_dir / "concat.txt"
    concat_txt.write_text("\n".join([f"file '{p.as_posix()}'" for p in segment_files]), encoding="utf-8")
    merged_file = tmp_dir / "merged.mp4"
    _run_ffmpeg(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt)]
        + _encode_args(render_cfg)
        + [str(merged_file)],
        "concat merge",
    )
    return _burn_subtitles(merged_file, subtitles_path, output_video_path)


def _burn_subtitles(input_video: Path, subtitles_path: Path, output_video: Path) -> Path:
    render_cfg = load_config().get("render", {})
    # Windows 安全转义：ffmpeg ass 滤镜路径。
    # 盘符冒号需转义，分隔符统一为斜杠。
    ass_filter_path = str(subtitles_path.resolve()).replace("\\", "/").replace(":", "\\:")
    ass_arg = f"ass='{ass_filter_path}'"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_video),
        "-vf",
        ass_arg,
        "-copyts",
    ] + _encode_args(render_cfg) + [str(output_video)]
    _run_ffmpeg(cmd, "subtitle burn-in")
    return output_video


def _encode_args(render_cfg: dict) -> list[str]:
    args = [
        "-c:v",
        str(render_cfg.get("video_codec", "libx264")),
        "-c:a",
        str(render_cfg.get("audio_codec", "aac")),
    ]
    if "video_profile" in render_cfg:
        args += ["-profile:v", str(render_cfg["video_profile"])]
    if "video_level" in render_cfg:
        args += ["-level:v", str(render_cfg["video_level"])]
    if "crf" in render_cfg:
        args += ["-crf", str(render_cfg["crf"])]
    if "preset" in render_cfg:
        args += ["-preset", str(render_cfg["preset"])]
    if "pixel_format" in render_cfg:
        args += ["-pix_fmt", str(render_cfg["pixel_format"])]
    if "movflags" in render_cfg:
        args += ["-movflags", str(render_cfg["movflags"])]
    return args


def _run_ffmpeg(cmd: list[str], step: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ExternalCommandError(f"FFmpeg {step} failed: {result.stderr}")


def _compute_keep_ranges(input_video_path: Path, edits: list[dict]) -> list[tuple[float, float | None]]:
    # 将 compress_pause 转换为删除尾部区域：
    # 保留 [start, start+target_duration]，删除 (start+target_duration, end]
    normalized_deletes = []
    for e in edits:
        if e.get("type") == "delete":
            normalized_deletes.append({"start": e["start"], "end": e["end"]})
        elif e.get("type") == "compress_pause":
            target = float(e.get("target_duration") or 0.0)
            delete_start = min(e["end"], e["start"] + max(0.0, target))
            if e["end"] > delete_start:
                normalized_deletes.append({"start": delete_start, "end": e["end"]})
    deletes = sorted(normalized_deletes, key=lambda x: x["start"])
    if not deletes:
        return [(0.0, None)]
    keeps = []
    cursor = 0.0
    for d in deletes:
        if d["start"] > cursor:
            keeps.append((cursor, d["start"]))
        cursor = max(cursor, d["end"])
    keeps.append((cursor, None))
    return keeps