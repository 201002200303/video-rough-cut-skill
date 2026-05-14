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
    """调用 LLM 提取全局语义上下文。"""
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
            summary=result.get("summary", ""),
            topic=result.get("topic", ""),
            speaker_aliases=result.get("speaker_aliases", []),
            canonical_speaker_name=result.get("canonical_speaker_name", ""),
            canonical_speaker_confidence=float(result.get("canonical_speaker_confidence", 0.0)),
            canonical_terms=result.get("canonical_terms", []),
        )
        canonical_info = ""
        if ctx.canonical_speaker_name and ctx.canonical_speaker_confidence > 0:
            canonical_info = f" canonical={ctx.canonical_speaker_name}({ctx.canonical_speaker_confidence:.0%})"
        logger.info(
            "Global context: topic=%s summary=%s... aliases=%d canonical_terms=%d%s",
            ctx.topic,
            ctx.summary[:40] if ctx.summary else "(无)",
            len(ctx.speaker_aliases),
            len(ctx.canonical_terms),
            canonical_info,
        )
    except ProviderError:
        logger.warning("Global context LLM call failed, using empty context")
        ctx = GlobalContext()

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(ctx.model_dump_json(indent=2), encoding="utf-8")

    return ctx
