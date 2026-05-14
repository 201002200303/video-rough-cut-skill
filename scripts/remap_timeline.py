"""根据编辑决策重映射转写时间线。"""

import json
from pathlib import Path

from core.utils import setup_logger
from schemas.models import EditDecisionFile
from schemas.models import Transcript, TranscriptSegment, TranscriptWord

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
        if seg.words:
            remapped_segments.extend(_remap_segment_by_words(seg, edit_decision_file.edits))
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
                        word_id=w.word_id,
                    )
                )
        text = "".join(w.word for w in words) if words and (clamped_start != seg.start or clamped_end != seg.end) else seg.text
        remapped_segments.append(
            TranscriptSegment(id=seg.id, start=new_start, end=new_end, text=text, words=words)
        )
    out = Transcript(language=transcript.language, segments=remapped_segments)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Remapped transcript saved: %s", output_path)
    return out


def _remap_segment_by_words(seg: TranscriptSegment, edits: list) -> list[TranscriptSegment]:
    kept_words = [word for word in seg.words if not _overlaps_delete(word.start, word.end, edits)]
    if not kept_words:
        return []

    chunks: list[list[TranscriptWord]] = []
    current: list[TranscriptWord] = []
    for word in kept_words:
        if current and _delete_between(current[-1].end, word.start, edits):
            chunks.append(current)
            current = []
        current.append(word)
    if current:
        chunks.append(current)

    remapped: list[TranscriptSegment] = []
    multi = len(chunks) > 1
    for idx, chunk in enumerate(chunks, start=1):
        words = []
        for word in chunk:
            ws = _map_time(word.start, edits)
            we = _map_time(word.end, edits)
            if we > ws:
                words.append(
                    TranscriptWord(
                        word=word.word,
                        start=ws,
                        end=we,
                        timestamp_source=word.timestamp_source,
                        word_id=word.word_id,
                    )
                )
        if not words:
            continue
        remapped.append(
            TranscriptSegment(
                id=f"{seg.id}_part{idx}" if multi else seg.id,
                start=words[0].start,
                end=words[-1].end,
                text="".join(word.word for word in words),
                words=words,
            )
        )
    return remapped


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


def _overlaps_delete(start: float, end: float, edits: list) -> bool:
    for e in edits:
        if e.type == "delete" and max(start, e.start) < min(end, e.end):
            return True
    return False


def _delete_between(start: float, end: float, edits: list) -> bool:
    if end <= start:
        return False
    for e in edits:
        if e.type == "delete" and max(start, e.start) < min(end, e.end):
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
