"""基于 FFmpeg silencedetect 的轻量 VAD 近似实现。"""

import json
import re
import subprocess
import wave
from pathlib import Path

from core.config import load_config
from core.exceptions import ExternalCommandError
from core.logging import setup_logger

logger = setup_logger(__name__)


def detect_vad(audio_path: Path, output_path: Path) -> dict:
    """检测非静音语音区间并写出 vad_segments.json。

    当前实现使用 FFmpeg silencedetect 作为轻量近似。它检测的是静音/非静音，
    不是严格的人声识别；有背景声时只能作为边界参考。
    """
    cfg = load_config().get("vad", {})
    noise_db = cfg.get("noise_db", "-35dB")
    min_silence_duration = float(cfg.get("min_silence_duration", 0.25))
    min_speech_duration = float(cfg.get("min_speech_duration", 0.15))
    duration = _audio_duration(audio_path)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(audio_path),
        "-af",
        f"silencedetect=noise={noise_db}:d={min_silence_duration}",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ExternalCommandError(f"ffmpeg silencedetect failed: {result.stderr}")
    silences = _parse_silences(result.stderr)
    speech_segments = _silences_to_speech(silences, duration, min_speech_duration)
    out = {
        "method": "ffmpeg_silencedetect",
        "timestamp_quality": "boundary_reference",
        "audio_path": str(audio_path),
        "duration": duration,
        "speech_segments": speech_segments,
        "silence_segments": [
            {"start": round(s, 3), "end": round(e, 3), "duration": round(e - s, 3)}
            for s, e in silences
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("VAD segments saved: %s (speech=%d silence=%d)", output_path, len(speech_segments), len(silences))
    return out


def _parse_silences(stderr: str) -> list[tuple[float, float]]:
    starts: list[float] = []
    silences: list[tuple[float, float]] = []
    for line in stderr.splitlines():
        m_start = re.search(r"silence_start:\s*([0-9.]+)", line)
        if m_start:
            starts.append(float(m_start.group(1)))
            continue
        m_end = re.search(r"silence_end:\s*([0-9.]+)", line)
        if m_end and starts:
            silences.append((starts.pop(0), float(m_end.group(1))))
    return silences


def _silences_to_speech(
    silences: list[tuple[float, float]],
    duration: float,
    min_speech_duration: float,
) -> list[dict]:
    if duration <= 0:
        return []
    speech = []
    cursor = 0.0
    for start, end in sorted(silences):
        if start > cursor and start - cursor >= min_speech_duration:
            speech.append({"start": round(cursor, 3), "end": round(start, 3), "duration": round(start - cursor, 3)})
        cursor = max(cursor, end)
    if duration > cursor and duration - cursor >= min_speech_duration:
        speech.append({"start": round(cursor, 3), "end": round(duration, 3), "duration": round(duration - cursor, 3)})
    return speech


def _audio_duration(audio_path: Path) -> float:
    try:
        with wave.open(str(audio_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or 16000
            return round(float(frames) / float(rate), 3)
    except Exception:
        return 0.0
