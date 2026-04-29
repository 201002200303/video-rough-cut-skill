"""输出产物路径管理。"""

from pathlib import Path

from core.exceptions import ValidationError


def ensure_output_dir(output_dir: str) -> Path:
    """创建并返回输出目录。

    参数:
        output_dir: 输出目录路径字符串。

    返回:
        输出目录的 Path 对象。

    异常:
        ValidationError: output_dir 为空时抛出。
    """
    if not output_dir:
        raise ValidationError("output_dir must not be empty")
    p = Path(output_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def job_output_paths(output_dir: str) -> dict[str, Path]:
    """返回输出目录内所有标准产物路径的字典。

    参数:
        output_dir: 输出目录路径字符串。

    返回:
        产物键名到 Path 对象的映射字典。
    """
    d = ensure_output_dir(output_dir)
    return {
        "audio": d / "audio.wav",
        "vad_segments": d / "vad_segments.json",
        "transcript": d / "transcript.json",
        "semantic_segments": d / "semantic_segments.json",
        "edit_decisions": d / "edit_decisions.json",
        "transcript_before_edit": d / "transcript_before_edit.md",
        "transcript_after_edit": d / "transcript_after_edit.md",
        "remapped_transcript": d / "remapped_transcript.json",
        "subtitles": d / "subtitles.ass",
        "edited_video": d / "edited_video_with_yellow_subtitles.mp4",
        "report": d / "edit_report.md",
    }


# 标准产物文件名（供参考）
ARTIFACT_NAMES = {
    "audio": "audio.wav",
    "vad_segments": "vad_segments.json",
    "transcript": "transcript.json",
    "semantic_segments": "semantic_segments.json",
    "edit_decisions": "edit_decisions.json",
    "transcript_before_edit": "transcript_before_edit.md",
    "transcript_after_edit": "transcript_after_edit.md",
    "remapped_transcript": "remapped_transcript.json",
    "subtitles": "subtitles.ass",
    "edited_video": "edited_video_with_yellow_subtitles.mp4",
    "report": "edit_report.md",
}