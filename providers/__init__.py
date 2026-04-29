"""提供者模块导出。"""

from providers.asr_base import ASRProvider
from providers.aliyun_asr import AliyunASRProvider

__all__ = ["ASRProvider", "AliyunASRProvider"]