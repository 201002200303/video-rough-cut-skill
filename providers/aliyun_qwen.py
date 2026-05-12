"""阿里云 Qwen（通义千问）LLM 提供者。"""

import json
import os

import requests

from core.utils import ProviderError
from core.utils import load_config
from core.utils import setup_logger
from providers.llm_base import LLMProvider

logger = setup_logger(__name__)


class AliyunQwenProvider(LLMProvider):
    """基于 DashScope 兼容接口的 LLM 提供者。"""

    def __init__(self, model: str = "qwen-plus-latest") -> None:
        cfg = load_config().get("aliyun", {}).get("llm", {})
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
        self.model = os.getenv("DASHSCOPE_LLM_MODEL", cfg.get("model", model))
        base_url = os.getenv(
            "DASHSCOPE_API_BASE_URL",
            cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
        self.endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self.temperature = float(cfg.get("temperature", 0.1))
        self.max_tokens = int(cfg.get("max_tokens", 2048))
        self.timeout_seconds = int(cfg.get("timeout_seconds", 60))

    def semantic_dedup(self, prompt: str) -> dict:
        """语义去重 JSON 调用（仅真实 API）。"""
        if not self.api_key:
            raise ProviderError("DASHSCOPE_API_KEY is required for real semantic_dedup")
        logger.info("Aliyun Qwen semantic_dedup using real API path")
        try:
            result = self._call_qwen(prompt)
            if "duplicate_groups" not in result:
                result["duplicate_groups"] = []
            if "review_needed" not in result:
                result["review_needed"] = []
            return result
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"LLM semantic_dedup failed: {exc}") from exc

    def _call_qwen(self, prompt: str, system_prompt: str = "You must output strict JSON only.") -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        resp = requests.post(self.endpoint, headers=headers, json=payload, timeout=self.timeout_seconds)
        if resp.status_code >= 400:
            raise ProviderError(f"Qwen API error status={resp.status_code}: {resp.text}")
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, str):
                normalized = content.strip()
                if normalized.startswith("```"):
                    # 剥离代码围栏标记如 ```json ... ```
                    normalized = normalized.strip("`")
                    if normalized.startswith("json"):
                        normalized = normalized[4:].strip()
                parsed = json.loads(normalized)
            else:
                parsed = json.loads(content)
            return parsed
        except Exception as exc:
            raise ProviderError(f"Qwen response JSON parse failed: {exc}; raw={str(data)[:1000]}")

    # ── V2.5 新增方法 ──────────────────────────────────────

    def analyze_global_context(self, prompt: str) -> dict:
        """Phase 3: 全局语义分析。"""
        return self._call_qwen(
            prompt,
            system_prompt=(
                "你只负责提取全局上下文，不要纠错，不要删内容，不要输出剪辑建议。"
                "重点找：说话人自称、领域词、专有名词、固定表达、疑似 ASR 高频错词。"
                "不确定的内容放入 uncertainties，不要自作主张。"
            ),
        )

    def screen_segment_issues(self, prompt: str) -> dict:
        """Phase 4: Segment 问题粗筛。"""
        return self._call_qwen(
            prompt,
            system_prompt=(
                "你只负责粗筛 segment 是否可能存在问题。"
                "不要输出具体修改方案。不要删除内容。"
                "每个 flagged segment 必须给 issue_types、priority、evidence。"
                "如果只是轻微口语表达，不要标记。"
            ),
        )

    def correct_window(self, prompt: str) -> dict:
        """Phase 6: 窗口内 ASR 纠错候选。"""
        return self._call_qwen(
            prompt,
            system_prompt=(
                "你只负责 ASR 纠错候选。禁止去重、删口误、润色、改写。"
                "每个 correction 必须包含 word_ids、from_text、to_text、confidence、evidence。"
                "from_text 必须能由 word_ids 在原始输入中拼出。"
                "没有高置信证据就不要输出。"
            ),
        )

    def dedup_window(self, prompt: str) -> dict:
        """Phase 7: 窗口内去重/口误删除候选。"""
        return self._call_qwen(
            prompt,
            system_prompt=(
                "你看到 corrected_view 是为了理解语义，但删除必须返回原始 source_word_id。"
                "你只负责发现：快速重复、false start、语义重述、残句、明显口气词片段。"
                "禁止修错字、补字、润色、改写。"
                "如果重复是强调、承接、解释递进，不要删除。"
                "宁可漏删，不要误删。"
            ),
        )