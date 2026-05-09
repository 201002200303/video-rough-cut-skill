"""使用 FFmpeg 渲染带字幕的编辑视频。"""

import subprocess
from pathlib import Path

from core.utils import load_config
from core.utils import ExternalCommandError
from core.utils import resolve_command
from core.utils import setup_logger
from schemas.models import VisualMetadata

logger = setup_logger(__name__)


def render_video(
    input_video_path: Path,
    edit_decisions: list[dict],
    subtitles_path: Path,
    output_video_path: Path,
    visual_metadata: VisualMetadata | dict | None = None,
    cover_ass_path: Path | None = None,
    cover_image_path: Path | None = None,
) -> Path:
    """根据编辑决策和字幕渲染最终视频。"""
    render_cfg = load_config().get("render", {})
    output_video_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_video_path.parent / "tmp_render"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    metadata = VisualMetadata.model_validate(visual_metadata) if visual_metadata else None
    main_output_path = (
        tmp_dir / "main_packaged.mp4"
        if metadata and metadata.enabled and metadata.insert_cover_seconds > 0
        else output_video_path
    )
    keep_ranges = _compute_keep_ranges(input_video_path, edit_decisions)
    if not keep_ranges:
        keep_ranges = [(0.0, None)]
    if len(keep_ranges) == 1 and keep_ranges[0][0] == 0.0 and keep_ranges[0][1] is None:
        _burn_subtitles(input_video_path, subtitles_path, main_output_path)
        return _finish_visual_packaging(
            main_output_path,
            output_video_path,
            tmp_dir,
            render_cfg,
            metadata,
            cover_ass_path,
            cover_image_path,
        )

    if _should_use_filter_complex(render_cfg, keep_ranges):
        _render_with_filter_complex(input_video_path, keep_ranges, subtitles_path, main_output_path, render_cfg)
        return _finish_visual_packaging(
            main_output_path,
            output_video_path,
            tmp_dir,
            render_cfg,
            metadata,
            cover_ass_path,
            cover_image_path,
        )

    _render_with_segment_files(input_video_path, keep_ranges, subtitles_path, main_output_path, tmp_dir, render_cfg)
    return _finish_visual_packaging(
        main_output_path,
        output_video_path,
        tmp_dir,
        render_cfg,
        metadata,
        cover_ass_path,
        cover_image_path,
    )


def _render_with_segment_files(
    input_video_path: Path,
    keep_ranges: list[tuple[float, float | None]],
    subtitles_path: Path,
    output_video_path: Path,
    tmp_dir: Path,
    render_cfg: dict,
) -> Path:
    segment_files = []
    for idx, (start, end) in enumerate(keep_ranges):
        seg_file = tmp_dir / f"seg_{idx:03d}.mp4"
        cmd = [
            resolve_command("ffmpeg"), "-y",
            "-ss", str(start),
            "-i", str(input_video_path),
        ]
        if end is not None:
            cmd += ["-t", str(max(0.0, end - start))]
        cmd += _encode_args(render_cfg, intermediate=True) + [str(seg_file)]
        _run_ffmpeg(cmd, "segment cut")
        segment_files.append(seg_file)
    concat_txt = tmp_dir / "concat.txt"
    concat_txt.write_text("\n".join([f"file '{p.as_posix()}'" for p in segment_files]), encoding="utf-8")
    merged_file = tmp_dir / "merged.mp4"
    _run_ffmpeg(
        [resolve_command("ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt)]
        + _encode_args(render_cfg, intermediate=True)
        + [str(merged_file)],
        "concat merge",
    )
    return _burn_subtitles(merged_file, subtitles_path, output_video_path)


def _should_use_filter_complex(render_cfg: dict, keep_ranges: list[tuple[float, float | None]]) -> bool:
    if str(render_cfg.get("strategy", "filter_complex")) != "filter_complex":
        return False
    max_segments = int(render_cfg.get("max_filter_complex_segments", 80))
    return 0 < len(keep_ranges) <= max_segments


def _render_with_filter_complex(
    input_video_path: Path,
    keep_ranges: list[tuple[float, float | None]],
    subtitles_path: Path,
    output_video_path: Path,
    render_cfg: dict,
) -> Path:
    filter_parts: list[str] = []
    concat_inputs: list[str] = []
    for idx, (start, end) in enumerate(keep_ranges):
        trim_args = f"start={_ffmpeg_num(start)}"
        if end is not None:
            trim_args += f":end={_ffmpeg_num(end)}"
        filter_parts.append(f"[0:v]trim={trim_args},setpts=PTS-STARTPTS[v{idx}]")
        filter_parts.append(f"[0:a]atrim={trim_args},asetpts=PTS-STARTPTS[a{idx}]")
        concat_inputs.append(f"[v{idx}][a{idx}]")
    filter_parts.append(
        f"{''.join(concat_inputs)}concat=n={len(keep_ranges)}:v=1:a=1[vcat][acat]"
    )
    filter_parts.append(f"[vcat]{_ass_filter_arg(subtitles_path)}[vout]")
    cmd = [
        resolve_command("ffmpeg"),
        "-y",
        "-i",
        str(input_video_path),
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[vout]",
        "-map",
        "[acat]",
    ] + _encode_args(render_cfg, intermediate=False) + [str(output_video_path)]
    _run_ffmpeg(cmd, "filter_complex cut/concat/subtitle")
    return output_video_path


def _burn_subtitles(input_video: Path, subtitles_path: Path, output_video: Path) -> Path:
    render_cfg = load_config().get("render", {})
    ass_arg = _ass_filter_arg(subtitles_path)
    cmd = [
        resolve_command("ffmpeg"),
        "-y",
        "-i",
        str(input_video),
        "-vf",
        ass_arg,
    ] + _encode_args(render_cfg, intermediate=False) + [str(output_video)]
    _run_ffmpeg(cmd, "subtitle burn-in")
    return output_video


def _finish_visual_packaging(
    main_video_path: Path,
    output_video_path: Path,
    tmp_dir: Path,
    render_cfg: dict,
    metadata: VisualMetadata | None,
    cover_ass_path: Path | None,
    cover_image_path: Path | None,
) -> Path:
    if (
        metadata
        and metadata.enabled
        and (metadata.generate_cover or metadata.insert_cover_seconds > 0)
        and cover_ass_path
        and cover_image_path
    ):
        _generate_cover_image(main_video_path, metadata, cover_ass_path, cover_image_path)
    if not metadata or not metadata.enabled or metadata.insert_cover_seconds <= 0:
        return main_video_path
    if not cover_image_path:
        raise ValueError("cover_image_path is required when insert_cover_seconds > 0")

    cover_segment_path = tmp_dir / "cover_intro.mp4"
    _create_cover_segment(cover_image_path, cover_segment_path, metadata.insert_cover_seconds, render_cfg)
    concat_txt = tmp_dir / "concat_with_cover.txt"
    concat_txt.write_text(
        "\n".join([f"file '{cover_segment_path.as_posix()}'", f"file '{main_video_path.as_posix()}'"]),
        encoding="utf-8",
    )
    _run_ffmpeg(
        [resolve_command("ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt)]
        + _encode_args(render_cfg, intermediate=False)
        + [str(output_video_path)],
        "cover concat",
    )
    return output_video_path


def _generate_cover_image(
    main_video_path: Path,
    metadata: VisualMetadata,
    cover_ass_path: Path,
    cover_image_path: Path,
) -> Path:
    cover_image_path.parent.mkdir(parents=True, exist_ok=True)
    base_frame_path = cover_image_path.parent / "tmp_render" / "cover_base.png"
    base_frame_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            resolve_command("ffmpeg"),
            "-y",
            "-ss",
            str(metadata.cover_frame_time),
            "-i",
            str(main_video_path),
            "-frames:v",
            "1",
            str(base_frame_path),
        ],
        "cover frame extract",
    )
    _run_ffmpeg(
        [
            resolve_command("ffmpeg"),
            "-y",
            "-i",
            str(base_frame_path),
            "-vf",
            _ass_filter_arg(cover_ass_path),
            "-frames:v",
            "1",
            str(cover_image_path),
        ],
        "cover burn-in",
    )
    return cover_image_path


def _create_cover_segment(
    cover_image_path: Path,
    output_path: Path,
    duration: float,
    render_cfg: dict,
) -> Path:
    _run_ffmpeg(
        [
            resolve_command("ffmpeg"),
            "-y",
            "-loop",
            "1",
            "-i",
            str(cover_image_path),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            str(duration),
            "-shortest",
        ]
        + _encode_args(render_cfg, intermediate=False)
        + [str(output_path)],
        "cover segment",
    )
    return output_path


def _ass_filter_arg(subtitles_path: Path) -> str:
    ass_filter_path = str(subtitles_path.resolve()).replace("\\", "/").replace(":", "\\:")
    return f"ass='{ass_filter_path}'"


def _ffmpeg_num(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _encode_args(render_cfg: dict, intermediate: bool = False) -> list[str]:
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
    crf_key = "intermediate_crf" if intermediate and "intermediate_crf" in render_cfg else "crf"
    preset_key = "intermediate_preset" if intermediate and "intermediate_preset" in render_cfg else "preset"
    if crf_key in render_cfg:
        args += ["-crf", str(render_cfg[crf_key])]
    if preset_key in render_cfg:
        args += ["-preset", str(render_cfg[preset_key])]
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
    render_cfg = load_config().get("render", {})
    min_keep_gap = float(render_cfg.get("min_keep_gap_between_deletes", 0.0))
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
    deletes = _merge_close_deletes(sorted(normalized_deletes, key=lambda x: x["start"]), min_keep_gap)
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


def _merge_close_deletes(deletes: list[dict], min_keep_gap: float) -> list[dict]:
    if not deletes:
        return []
    merged = [dict(deletes[0])]
    for cur in deletes[1:]:
        last = merged[-1]
        if cur["start"] <= last["end"] + min_keep_gap:
            last["end"] = max(last["end"], cur["end"])
        else:
            merged.append(dict(cur))
    return merged
