"""配置加载与管理。"""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from core.exceptions import ConfigError

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.default.yaml"

_cached_config: dict[str, Any] | None = None


def load_config() -> dict[str, Any]:
    """从 config.default.yaml 加载配置，若 VIDEO_SKILL_CONFIG 已设置则叠加环境配置。

    返回:
        合并后的配置字典。
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    if not _DEFAULT_CONFIG_PATH.exists():
        raise ConfigError(f"Default config not found: {_DEFAULT_CONFIG_PATH}")

    base = yaml.safe_load(_DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))

    env_config_path = os.getenv("VIDEO_SKILL_CONFIG")
    if env_config_path:
        p = Path(env_config_path)
        if not p.exists():
            raise ConfigError(f"VIDEO_SKILL_CONFIG path not found: {p}")
        overlay = yaml.safe_load(p.read_text(encoding="utf-8"))
        if overlay:
            _deep_merge(base, overlay)

    _cached_config = base
    return base


def reload_config() -> dict[str, Any]:
    """强制重新加载配置（清除缓存）。"""
    global _cached_config
    _cached_config = None
    return load_config()


def load_env() -> None:
    """从 .env 文件加载环境变量。"""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()


def _deep_merge(base: dict, overlay: dict) -> None:
    """递归合并 overlay 到 base（原地修改 base）。"""
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value