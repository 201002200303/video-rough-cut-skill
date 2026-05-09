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

    def _call_qwen(self, prompt: str) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You must output strict JSON only."},
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