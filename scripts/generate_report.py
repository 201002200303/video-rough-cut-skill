"""生成 Markdown 格式的编辑报告。"""

from pathlib import Path

from core.logging import setup_logger

logger = setup_logger(__name__)


def generate_report(
    input_video_path: Path,
    output_video_path: Path,
    edit_decision_file: dict,
    output_path: Path,
) -> Path:
    edits = edit_decision_file.get("edits", [])
    review_needed = edit_decision_file.get("review_needed", [])
    delete_count = len([e for e in edits if e.get("type") == "delete"])
    compress_count = len([e for e in edits if e.get("type") == "compress_pause"])

    lines = [
        "# Edit Report",
        "",
        f"- Input Video: `{input_video_path}`",
        f"- Output Video: `{output_video_path}`",
        f"- Total Edits: {len(edits)}",
        f"- Delete Count: {delete_count}",
        f"- Compress Pause Count: {compress_count}",
        f"- Review Needed Count: {len(review_needed)}",
        "",
        "## Edit Details",
        "",
    ]
    for e in edits:
        lines.extend(
            [
                f"- type: `{e.get('type')}`",
                f"  - start: {e.get('start')}",
                f"  - end: {e.get('end')}",
                f"  - source: `{e.get('source')}`",
                f"  - reason: {e.get('reason')}",
                f"  - confidence: {e.get('confidence')}",
            ]
        )
    lines.extend(["", "## Risk Notes", ""])
    if review_needed:
        lines.append("- 存在 review_needed 项，建议人工复核。")
    low_conf = [e for e in edits if e.get("confidence") is not None and e.get("confidence") < 0.85]
    if low_conf:
        lines.append("- 存在低置信度语义去重动作，建议人工复核。")
    if not review_needed and not low_conf:
        lines.append("- 当前无明显高风险项。")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Report generated: %s", output_path)
    return output_path