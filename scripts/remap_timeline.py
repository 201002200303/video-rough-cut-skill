"""根据编辑决策重映射转写时间线。"""

from pathlib import Path

from core.logging import setup_logger
from schemas.edit_decision import EditDecisionFile
from schemas.transcript import Transcript, TranscriptSegment, TranscriptWord

logger = setup_logger(__name__)


def remap_timeline(
    transcript: Transcript,
    edit_decision_file: EditDecisionFile,
    output_path: Path,
) -> Transcript:
    """应用 delete/compress_pause 编辑决策，输出重映射后的转写结果。"""
    remapped_segments = []
    for seg in transcript.segments:
        if _inside_delete(seg.start, seg.end, edit_decision_file.edits):
            continue
        # 截断片段边界以排除删除区域，而非整段丢弃。
        clamped_start, clamped_end = _clamp_to_keep(seg.start, seg.end, edit_decision_file.edits)
        if clamped_end <= clamped_start:
            continue
        new_start = _map_time(clamped_start, edit_decision_file.edits)
        new_end = _map_time(clamped_end, edit_decision_file.edits)
        if new_end <= new_start:
            continue
        words = []
        for w in seg.words:
            if _inside_delete(w.start, w.end, edit_decision_file.edits):
                continue
            wc_start, wc_end = _clamp_to_keep(w.start, w.end, edit_decision_file.edits)
            if wc_end <= wc_start:
                continue
            ws = _map_time(wc_start, edit_decision_file.edits)
            we = _map_time(wc_end, edit_decision_file.edits)
            if we > ws:
                words.append(
                    TranscriptWord(
                        word=w.word,
                        start=ws,
                        end=we,
                        timestamp_source=w.timestamp_source,
                    )
                )
        text = "".join(w.word for w in words) if words and (clamped_start != seg.start or clamped_end != seg.end) else seg.text
        remapped_segments.append(
            TranscriptSegment(id=seg.id, start=new_start, end=new_end, text=text, words=words)
        )
    out = Transcript(language=transcript.language, segments=remapped_segments)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(out.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Remapped transcript saved: %s", output_path)
    return out


def _map_time(t: float, edits: list) -> float:
    shift = 0.0
    for e in edits:
        if e.type == "delete":
            if t >= e.end:
                shift += e.end - e.start
        elif e.type == "compress_pause":
            if t >= e.end:
                shift += (e.end - e.start) - (e.target_duration or 0.0)
    return max(0.0, t - shift)


def _inside_delete(start: float, end: float, edits: list) -> bool:
    for e in edits:
        if e.type == "delete" and start >= e.start and end <= e.end:
            return True
    return False


def _clamp_to_keep(start: float, end: float, edits: list) -> tuple[float, float]:
    """截断 [start, end] 使其不与任何删除区域重叠。

    当片段与删除区域部分重叠时，在删除边界处截断而非整段丢弃。
    仅保留不在任何删除区域内的部分；若多个删除区域分割片段，
    则保留最大的连续非删除块。
    """
    for e in edits:
        if e.type != "delete":
            continue
        # 片段尾部进入删除区域：截断结束到删除起点。
        if start < e.start < end:
            end = e.start
        # 片段头部进入删除区域：截断起点到删除终点。
        if start < e.end < end:
            start = e.end
    return start, end