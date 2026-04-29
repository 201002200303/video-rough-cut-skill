"""FFmpeg 媒体工具：可用性检查、视频探测与音频提取。"""

import json
import subprocess
from pathlib import Path

from core.config import load_config
from core.exceptions import ExternalCommandError
from core.logging import setup_logger

logger = setup_logger(__name__)


def check_ffmpeg_available() -> None:
    """检查 ffmpeg 和 ffprobe 是否在 PATH 中可用。

    异常:
        ExternalCommandError: 任一命令不可用或返回非零状态码时抛出。
    """
    for cmd in (["ffmpeg", "-version"], ["ffprobe", "-version"]):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise ExternalCommandError(
                f"Command unavailable: {' '.join(cmd)}; stderr={result.stderr}"
            )


def probe_video(input_video_path: Path) -> dict:
    """使用 ffprobe 探测视频元数据。

    参数:
        input_video_path: 输入视频路径。

    返回:
        解析后的 ffprobe JSON 字典。

    异常:
        ExternalCommandError: ffprobe 失败或输出非有效 JSON 时抛出。
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(input_video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ExternalCommandError(
            f"ffprobe failed (returncode={result.returncode}): {result.stderr}"
        )
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ExternalCommandError(f"ffprobe returned invalid JSON: {exc}") from exc


def extract_audio(input_video_path: Path, output_audio_path: Path) -> Path:
    """使用 ffmpeg 从视频中提取 16k 单声道 WAV 音频。

    推荐命令：
    ffmpeg -y -i input.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 audio.wav

    参数:
        input_video_path: 输入视频文件路径。
        output_audio_path: 输出 WAV 音频路径。

    返回:
        输出音频路径。

    异常:
        ExternalCommandError: ffmpeg 命令失败或输出文件缺失时抛出。
    """
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    asr_cfg = load_config().get("aliyun", {}).get("asr", {})
    sample_rate = str(int(asr_cfg.get("sample_rate", 16000)))
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        sample_rate,
        "-ac",
        "1",
        str(output_audio_path),
    ]
    logger.info("Extracting audio with command: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ExternalCommandError(
            f"ffmpeg extract_audio failed (returncode={result.returncode}): {result.stderr}"
        )
    if not output_audio_path.exists():
        raise ExternalCommandError(f"Audio extraction output not found: {output_audio_path}")
    return output_audio_path