"""LLM 提供者抽象基类。"""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """LLM 提供者抽象基类。"""

    @abstractmethod
    def semantic_dedup(self, prompt: str) -> dict:
        """返回语义去重的严格 JSON 结果。"""
        ...