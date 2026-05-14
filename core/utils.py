"""Shared utilities for the video rough-cut skill."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency fallback for lean local test envs
    def load_dotenv(*args, **kwargs) -> bool:
        return False


class SkillError(Exception):
    """Base class for skill errors."""


class ExternalCommandError(SkillError):
    """Raised when an external command such as FFmpeg fails."""


class ProviderError(SkillError):
    """Raised when an ASR or LLM provider call fails."""


class ValidationError(SkillError):
    """Raised when input validation fails."""


class ConfigError(SkillError):
    """Raised when configuration is invalid or missing."""


_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.default.yaml"
_cached_config: dict[str, Any] | None = None


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    return logger


def load_config() -> dict[str, Any]:
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    if not _DEFAULT_CONFIG_PATH.exists():
        raise ConfigError(f"Default config not found: {_DEFAULT_CONFIG_PATH}")

    base = yaml.safe_load(_DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    env_config_path = os.getenv("VIDEO_SKILL_CONFIG")
    if env_config_path:
        path = Path(env_config_path)
        if not path.exists():
            raise ConfigError(f"VIDEO_SKILL_CONFIG path not found: {path}")
        overlay = yaml.safe_load(path.read_text(encoding="utf-8"))
        if overlay:
            deep_merge(base, overlay)

    _cached_config = base
    return base


def reload_config() -> dict[str, Any]:
    global _cached_config
    _cached_config = None
    return load_config()


def load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()


def resolve_command(command: str) -> str:
    """Return an executable path suitable for subprocess on the current OS."""
    resolved = shutil.which(command)
    if resolved:
        return resolved

    local_bin = Path(__file__).resolve().parent.parent / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    if os.name == "nt":
        for suffix in (".exe", ".cmd", ".bat"):
            candidate = local_bin / f"{command}{suffix}"
            if candidate.exists():
                return str(candidate)
    else:
        candidate = local_bin / command
        if candidate.exists():
            return str(candidate)

    if os.name == "nt":
        for suffix in (".exe", ".cmd", ".bat"):
            resolved = shutil.which(command + suffix)
            if resolved:
                return resolved
        # 搜索常见 Windows 安装路径
        exe_name = f"{command}.exe"
        search_roots = [
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"),
            r"C:\ProgramData\chocolatey\bin",
            r"C:\ffmpeg\bin",
            r"C:\Program Files\ffmpeg\bin",
            r"C:\Program Files (x86)\ffmpeg\bin",
        ]
        for root in search_roots:
            if not os.path.isdir(root):
                continue
            if os.path.isfile(os.path.join(root, exe_name)):
                return os.path.join(root, exe_name)
            # winget: 递归搜索子目录（最多3层）
            try:
                for entry in os.scandir(root):
                    if entry.is_dir():
                        for dirpath, _dirnames, filenames in os.walk(entry.path):
                            if exe_name in filenames:
                                return os.path.join(dirpath, exe_name)
                            # 限制深度，避免搜索太深
                            depth = dirpath[len(entry.path):].count(os.sep)
                            if depth >= 3:
                                _dirnames.clear()
            except OSError:
                continue

    return command


def deep_merge(base: dict, overlay: dict) -> None:
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            deep_merge(base[key], value)
        else:
            base[key] = value


def ensure_output_dir(output_dir: str) -> Path:
    if not output_dir:
        raise ValidationError("output_dir must not be empty")
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_output_paths(output_dir: str) -> dict[str, Path]:
    directory = ensure_output_dir(output_dir)
    return {
        "audio": directory / "audio.wav",
        "vad_segments": directory / "vad_segments.json",
        "transcript": directory / "transcript.json",
        "semantic_segments": directory / "semantic_segments.json",
        "utterance_units": directory / "utterance_units.json",
        "edit_decisions": directory / "edit_decisions.json",
        "transcript_before_edit": directory / "transcript_before_edit.md",
        "transcript_after_edit": directory / "transcript_after_edit.md",
        "remapped_transcript": directory / "remapped_transcript.json",
        "subtitles": directory / "subtitles.ass",
        "visual_metadata": directory / "visual_metadata.json",
        "visual_overlay_ass": directory / "visual_overlay.ass",
        "cover_ass": directory / "cover.ass",
        "cover_image": directory / "cover.png",
        "edited_video": directory / "edited_video_with_yellow_subtitles.mp4",
        "report": directory / "edit_report.md",
        # V2.5 artifacts
        "source_words": directory / "source_words.json",
        "source_segments": directory / "source_segments.json",
        "global_context": directory / "global_context.json",
        "segment_issues": directory / "segment_issues.json",
        "windows": directory / "windows.json",
        "display_patches": directory / "display_patches.json",
        "deletion_candidates": directory / "deletion_candidates.json",
        "remapped_words": directory / "remapped_words.json",
    }


ARTIFACT_NAMES = {
    "audio": "audio.wav",
    "vad_segments": "vad_segments.json",
    "transcript": "transcript.json",
    "semantic_segments": "semantic_segments.json",
    "utterance_units": "utterance_units.json",
    "edit_decisions": "edit_decisions.json",
    "transcript_before_edit": "transcript_before_edit.md",
    "transcript_after_edit": "transcript_after_edit.md",
    "remapped_transcript": "remapped_transcript.json",
    "subtitles": "subtitles.ass",
    "visual_metadata": "visual_metadata.json",
    "visual_overlay_ass": "visual_overlay.ass",
    "cover_ass": "cover.ass",
    "cover_image": "cover.png",
    "edited_video": "edited_video_with_yellow_subtitles.mp4",
    "report": "edit_report.md",
    # V2.5 artifacts
    "source_words": "source_words.json",
    "source_segments": "source_segments.json",
    "global_context": "global_context.json",
    "segment_issues": "segment_issues.json",
    "windows": "windows.json",
    "display_patches": "display_patches.json",
    "deletion_candidates": "deletion_candidates.json",
    "remapped_words": "remapped_words.json",
}
