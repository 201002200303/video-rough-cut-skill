"""LLM 提供者抽象基类。"""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """LLM 提供者抽象基类。"""

    @abstractmethod
    def semantic_dedup(self, prompt: str) -> dict:
        """返回语义去重的严格 JSON 结果。"""
        ...

    # ── V2.5 新增方法 ──────────────────────────────────────

    def analyze_global_context(self, prompt: str) -> dict:
        """Phase 3: 全局语义分析 — 话题、说话人、领域词、高频错词。"""
        return self.semantic_dedup(prompt)

    def screen_segment_issues(self, prompt: str) -> dict:
        """Phase 4: Segment 问题粗筛 — 标记需要进入窗口的 segment。"""
        return self.semantic_dedup(prompt)

    def correct_window(self, prompt: str) -> dict:
        """Phase 6: 窗口内 ASR 纠错 — 输出 DisplayPatch 候选。"""
        return self.semantic_dedup(prompt)

    def dedup_window(self, prompt: str) -> dict:
        """Phase 7: 窗口内去重/口误删除 — 输出 DeletionCandidate。"""
        return self.semantic_dedup(prompt)