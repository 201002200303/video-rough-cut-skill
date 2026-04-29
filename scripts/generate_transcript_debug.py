"""生成剪辑前后逐句时间轴调试文件。"""

from pathlib import Path

from core.logging import setup_logger
from schemas.edit_decision import EditDecisionFile
from schemas.transcript import Transcript

logger = setup_logger(__name__)


def generate_transcript_debug_files(
    before_transcript: Transcript,
    after_transcript: Transcript,
    edit_decision_file: EditDecisionFile,
    before_output_path: Path,
    after_output_path: Path,
) -> tuple[Path, Path]:
    """输出剪辑前/剪辑后的逐句时间轴，便于人工检查边界与策略。"""
    edits = edit_decision_file.edits
    before_lines = _timeline_lines(
        title="剪辑前逐句时间轴",
        transcript=before_transcript,
        edits=edits,
        source_transcript=before_transcript,
        include_strategy=bool(edits),
    )
    after_lines = _timeline_lines(
        title="剪辑后逐句时间轴",
        transcript=after_transcript,
        edits=edits,
        source_transcript=before_transcript,
        include_strategy=bool(edits),
    )
    before_output_path.parent.mkdir(parents=True, exist_ok=True)
    before_output_path.write_text("\n".join(before_lines), encoding="utf-8")
    after_output_path.write_text("\n".join(after_lines), encoding="utf-8")
    logger.info("Transcript debug files generated: %s, %s", before_output_path, after_output_path)
    return before_output_path, after_output_path


def _timeline_lines(
    title: str,
    transcript: Transcript,
    edits: list,
    source_transcript: Transcript,
    include_strategy: bool,
) -> list[str]:
    lines = [
        f"# {title}",
        "",
        "## 连续语句",
        "",
        "| # | segment_id | start | end | duration | text |",
        "|---|---|---:|---:|---:|---|",
    ]
    for idx, seg in enumerate(transcript.segments, start=1):
        lines.append(
            f"| {idx} | `{seg.id}` | {_fmt(seg.start)} | {_fmt(seg.end)} | {_fmt(seg.end - seg.start)} | {_escape(seg.text)} |"
        )
    lines.extend(["", "## 词/短语边界", ""])
    for idx, seg in enumerate(transcript.segments, start=1):
        lines.extend(
            [
                f"### {idx}. `{seg.id}` {_fmt(seg.start)}-{_fmt(seg.end)}",
                "",
                f"> {_escape(seg.text)}",
                "",
            ]
        )
        if not seg.words:
            lines.extend(["- 无 word 级边界。", ""])
            continue
        for w in seg.words:
            source = getattr(w, "timestamp_source", "estimated")
            lines.append(f"- `{_fmt(w.start)}-{_fmt(w.end)}` `{source}` {w.word}")
        lines.append("")

    if include_strategy:
        lines.extend(_strategy_lines(edits, source_transcript))
    return lines


def _strategy_lines(edits: list, source_transcript: Transcript) -> list[str]:
    lines = ["## 实际剪辑策略", ""]
    for idx, edit in enumerate(edits, start=1):
        affected = _text_in_range(source_transcript, edit.start, edit.end)
        lines.extend(
            [
                f"### {idx}. `{edit.type}` {_fmt(edit.start)}-{_fmt(edit.end)}",
                "",
                f"- 来源：`{edit.source}`",
                f"- 影响文本：{_escape(affected) if affected else '未匹配到文本'}",
                f"- 原因：{edit.reason}",
                f"- 置信度：{edit.confidence}",
                f"- 判断标准：{_criterion(edit)}",
                "",
            ]
        )
    return lines


def _text_in_range(transcript: Transcript, start: float, end: float) -> str:
    parts: list[str] = []
    for seg in transcript.segments:
        if max(start, seg.start) >= min(end, seg.end):
            continue
        words = [w.word for w in seg.words if max(start, w.start) < min(end, w.end)]
        parts.append("".join(words) if words else seg.text)
    return " / ".join(parts)


def _criterion(edit) -> str:
    if edit.source == "pause_detector":
        return "相邻语句/真实边界停顿达到阈值后压缩，保留 target_duration。"
    if edit.source == "semantic_dedup":
        return "LLM 判断为重复表达，并通过最长删除、时间戳来源、边界解析等护栏。"
    if edit.source == "content_cleanup":
        return "LLM 判断为低价值/语气词/幻听片段，并通过时间戳来源和边界解析护栏。"
    return "由对应 source 生成，并已进入最终 edit_decisions。"


def _fmt(value: float) -> str:
    return f"{value:.3f}"


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
