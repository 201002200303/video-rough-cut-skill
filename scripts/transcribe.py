"""ASR 转写入口。"""

import json
from pathlib import Path

from core.utils import ProviderError
from core.utils import load_config
from core.utils import setup_logger
from providers.aliyun_asr import AliyunASRProvider
from providers.funasr_asr import FunASRProvider
from schemas.models import Transcript

logger = setup_logger(__name__)


def _get_provider(provider_name: str):
    name = provider_name.lower().strip()
    if name == "funasr":
        return FunASRProvider()
    if name == "aliyun":
        return AliyunASRProvider()
    raise ProviderError(f"Unsupported ASR provider: {provider_name}")


def transcribe_audio(
    audio_path: Path,
    transcript_path: Path,
    provider_name: str | None = None,
) -> Transcript:
    """使用指定 provider 将音频转写为 transcript.json。

    参数:
        audio_path: 输入音频 WAV 路径。
        transcript_path: 输出 transcript.json 路径。
        provider_name: ASR 提供者名称，默认 aliyun。

    返回:
        已校验的 Transcript 对象。
    """
    cfg = load_config().get("asr", {})
    selected_provider = provider_name or cfg.get("provider", "funasr")
    fallback_provider = cfg.get("fallback_provider", "aliyun")
    allow_fallback = bool(cfg.get("allow_fallback", False))
    try:
        provider = _get_provider(selected_provider)
        transcript = provider.transcribe(audio_path=audio_path, output_path=transcript_path)
    except ProviderError as exc:
        logger.error("ASR provider %s failed: %s", selected_provider, exc)
        if not allow_fallback or not fallback_provider or fallback_provider == selected_provider:
            raise
        logger.warning(
            "ASR provider %s failed; falling back to %s. Output timestamps may be estimated.",
            selected_provider,
            fallback_provider,
        )
        provider = _get_provider(fallback_provider)
        transcript = provider.transcribe(audio_path=audio_path, output_path=transcript_path)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(
        json.dumps(transcript.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Transcript written: %s", transcript_path)
    return transcript
