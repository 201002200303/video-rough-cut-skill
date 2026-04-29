"""ASR 转写入口。"""

from pathlib import Path

from core.exceptions import ProviderError
from core.logging import setup_logger
from providers.aliyun_asr import AliyunASRProvider
from schemas.transcript import Transcript

logger = setup_logger(__name__)


def _get_provider(provider_name: str):
    name = provider_name.lower().strip()
    if name == "aliyun":
        return AliyunASRProvider()
    raise ProviderError(f"Unsupported ASR provider: {provider_name}")


def transcribe_audio(
    audio_path: Path,
    transcript_path: Path,
    provider_name: str = "aliyun",
) -> Transcript:
    """使用指定 provider 将音频转写为 transcript.json。

    参数:
        audio_path: 输入音频 WAV 路径。
        transcript_path: 输出 transcript.json 路径。
        provider_name: ASR 提供者名称，默认 aliyun。

    返回:
        已校验的 Transcript 对象。
    """
    provider = _get_provider(provider_name)
    transcript = provider.transcribe(audio_path=audio_path, output_path=transcript_path)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(
        transcript.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Transcript written: %s", transcript_path)
    return transcript