"""生成 Markdown 格式的编辑报告。V2 + V2.5 兼容。"""

from pathlib import Path

from core.utils import setup_logger

logger = setup_logger(__name__)


def generate_report(
    input_video_path: Path,
    output_video_path: Path,
    edit_decision_file: dict,
    output_path: Path,
    display_patches_count: int | None = None,
    deletion_candidates_count: int | None = None,
) -> Path:
    edits = edit_decision_file.get("edits", [])
    review_needed = edit_decision_file.get("review_needed", [])
    delete_count = len([e for e in edits if e.get("type") == "delete"])
    compress_count = len([e for e in edits if e.get("type") == "compress_pause"])

    # V2.5: 按来源分类删除
    delete_by_source: dict[str, int] = {}
    for e in edits:
        if e.get("type") == "delete":
            src = e.get("source", "unknown")
            delete_by_source[src] = delete_by_source.get(src, 0) + 1

    total_delete_duration = sum(
        e.get("end", 0.0) - e.get("start", 0.0)
        for e in edits if e.get("type") == "delete"
    )

    lines = [
        "# 剪辑报告",
        "",
        "## 概要",
        "",
        f"- 输入视频: `{input_video_path}`",
        f"- 输出视频: `{output_video_path}`",
        f"- 编辑总数: {len(edits)}",
        f"  - 删除: {delete_count} | 停顿压缩: {compress_count} | 待复核: {len(review_needed)}",
        f"  - 累计删除时长: {total_delete_duration:.1f}s",
    ]
    if delete_by_source:
        lines.append(f"  - 删除来源: {' | '.join(f'{k}:{v}' for k, v in sorted(delete_by_source.items()))}")
    if display_patches_count is not None:
        lines.append(f"- 字幕纠错补丁 (DisplayPatch): {display_patches_count} 个")
    if deletion_candidates_count is not None:
        lines.append(f"- 删除候选 (DeletionCandidate): {deletion_candidates_count} 个")
    lines.append("")

    lines.extend(["## 编辑明细", ""])
    for i, e in enumerate(edits):
        lines.extend(
            [
                f"### {i + 1}. {_type_label(e.get('type'))} — {e.get('source', 'unknown')}",
                "",
                f"- 时间: {e.get('start'):.2f}s → {e.get('end'):.2f}s ({(e.get('end', 0) - e.get('start', 0)):.2f}s)",
                f"- 原因: {e.get('reason', '(无)')}",
                f"- 置信度: {e.get('confidence')}",
            ]
        )
        if e.get("target_duration") is not None:
            lines.append(f"- 压缩目标: {e.get('target_duration')}s")
        lines.append("")

    lines.extend(["## 风险提示", ""])
    if review_needed:
        lines.append("- ⚠️ 存在 review_needed 项，建议人工复核。")
        for r in review_needed:
            lines.append(f"  - {r}")
    low_conf = [e for e in edits if e.get("confidence") is not None and e.get("confidence") < 0.85]
    if low_conf:
        lines.append(f"- ⚠️ 存在 {len(low_conf)} 个低置信度编辑 (confidence < 0.85)，建议人工复核。")
    if not review_needed and not low_conf:
        lines.append("- ✅ 当前无明显高风险项。")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("报告已生成: %s", output_path)
    return output_path


def _type_label(t: str) -> str:
    return {"delete": "🗑 删除", "compress_pause": "⏸ 压缩停顿"}.get(t, t)