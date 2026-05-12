"""Phase 3: 全局语义分析 — LLM 提取话题、说话人、领域词、高频错词。"""

from __future__ import annotations

import json
from pathlib import Path

from core.utils import load_config, setup_logger, ProviderError
from providers.aliyun_qwen import AliyunQwenProvider
from schemas.models import GlobalContext

logger = setup_logger(__name__)


def analyze_global_context(
    source_segments_text: str,
    global_context_prompt_path: Path,
    output_path: Path | None = None,
) -> GlobalContext:
    """调用 LLM 提取全局语义上下文。

    Args:
        source_segments_text: 拼接后的全文文本。
        global_context_prompt_path: prompt 模板路径。
        output_path: 可选的输出路径。

    Returns:
        GlobalContext 包含 topic, speaker_aliases, domain_terms 等。
    """
    cfg = load_config().get("global_context", {})
    if not bool(cfg.get("enabled", True)):
        logger.info("Global context analysis disabled")
        return GlobalContext()

    provider = AliyunQwenProvider()
    template = global_context_prompt_path.read_text(encoding="utf-8")
    prompt = template.replace("{{transcript_text}}", source_segments_text)

    try:
        result = provider.analyze_global_context(prompt)
        ctx = GlobalContext(
            topic=result.get("topic", ""),
            speaker_aliases=result.get("speaker_aliases", []),
            confirmed_terms=result.get("confirmed_terms", []),
            domain_terms=result.get("domain_terms", []),
            possible_misrecognitions=result.get("possible_misrecognitions", []),
            uncertain_items=result.get("uncertain_items", []),
        )
        logger.info(
            "Global context: topic=%s aliases=%d terms=%d misrecognitions=%d",
            ctx.topic,
            len(ctx.speaker_aliases),
            len(ctx.domain_terms),
            len(ctx.possible_misrecognitions),
        )
    except ProviderError:
        logger.warning("Global context LLM call failed, using empty context")
        ctx = GlobalContext()

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(ctx.model_dump_json(indent=2), encoding="utf-8")

    return ctx
