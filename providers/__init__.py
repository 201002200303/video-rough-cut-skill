"""提供者模块导出。"""

from providers.asr_base import ASRProvider
from providers.aliyun_asr import AliyunASRProvider
from providers.funasr_asr import FunASRProvider

__all__ = ["ASRProvider", "AliyunASRProvider", "FunASRProvider"]
