"""ASR 提供者抽象接口。"""

from abc import ABC, abstractmethod
from pathlib import Path

from schemas.models import Transcript


class ASRProvider(ABC):
    """ASR 提供者抽象基类。"""

    @abstractmethod
    def transcribe(self, audio_path: Path, output_path: Path) -> Transcript:
        """转写音频并返回已校验的 Transcript。"""
        ...