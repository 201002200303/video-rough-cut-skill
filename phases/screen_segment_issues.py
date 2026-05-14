"""Phase 4: Segment 问题粗筛 — LLM 扫描哪些 segment 需要进入窗口精修。"""

from __future__ import annotations

import json
from pathlib import Path

from core.utils import load_config, setup_logger, ProviderError
from providers.aliyun_qwen import AliyunQwenProvider
from schemas.models import GlobalContext, SegmentIssue, SegmentIssueFile, SourceSegment

logger = setup_logger(__name__)


def screen_segment_issues(
    source_segments: list[SourceSegment],
    global_context: GlobalContext,
    screening_prompt_path: Path,
    output_path: Path | None = None,
) -> SegmentIssueFile:
    """调用 LLM 粗筛哪些 segment 可能存在 ASR 错误或重复/口误。

    Args:
        source_segments: 全部 source segment。
        global_context: Phase 3 输出的全局上下文。
        screening_prompt_path: prompt 模板路径。
        output_path: 可选的输出路径。

    Returns:
        SegmentIssueFile 包含标记的问题 segment。
    """
    cfg = load_config().get("screening", {})
    if not bool(cfg.get("enabled", True)):
        logger.info("Segment issue screening disabled")
        return SegmentIssueFile()

    min_priority = cfg.get("min_priority", "medium")

    segments_json = json.dumps(
        [
            {
                "segment_id": s.segment_id,
                "text": s.text,
                "start": s.start,
                "end": s.end,
            }
            for s in source_segments
        ],
        ensure_ascii=False,
    )

    provider = AliyunQwenProvider()
    template = screening_prompt_path.read_text(encoding="utf-8")
    prompt = template.replace("{{segments_json}}", segments_json).replace(
        "{{global_context}}", global_context.model_dump_json(indent=2)
    )

    raw_result: dict | None = None
    rejected_items: list[dict] = []

    try:
        raw_result = provider.screen_segment_issues(prompt)
        issues = []
        for item in raw_result.get("issues", []):
            priority = item.get("priority", "low")
            if _priority_meets(priority, min_priority):
                issues.append(
                    SegmentIssue(
                        segment_id=item.get("segment_id", ""),
                        issue_types=item.get("issue_types", []),
                        priority=priority,
                        evidence=item.get("evidence", ""),
                    )
                )
            else:
                rejected_items.append({
                    "segment_id": item.get("segment_id", ""),
                    "priority": priority,
                    "reject_reason": f"priority '{priority}' below min '{min_priority}'",
                    "issue_types": item.get("issue_types", []),
                    "evidence": item.get("evidence", ""),
                })
        logger.info("Screening flagged %d segments for windows", len(issues))
    except ProviderError:
        logger.warning("Segment screening LLM call failed")
        issues = []

    out = SegmentIssueFile(issues=issues)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(out.model_dump_json(indent=2), encoding="utf-8")

        # 保存原始 LLM 返回（供排查筛查分类决策）
        debug_path = output_path.parent / f"{output_path.stem}_screening_raw.json"
        debug_data = {
            "prompt_size": len(prompt),
            "raw_llm_response": raw_result,
            "accepted_count": len(issues),
            "rejected_count": len(rejected_items),
            "rejected": rejected_items,
        }
        debug_path.write_text(
            json.dumps(debug_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Screening raw response saved: %s", debug_path)

    return out


def _priority_meets(priority: str, min_priority: str) -> bool:
    order = {"high": 3, "medium": 2, "low": 1}
    return order.get(priority, 0) >= order.get(min_priority, 0)
