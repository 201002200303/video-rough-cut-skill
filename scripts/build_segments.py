"""将转写片段合并为语义段。"""

from core.logging import setup_logger
from schemas.segment import SemanticSegment
from schemas.transcript import Transcript

logger = setup_logger(__name__)


def build_semantic_segments(
    transcript: Transcript,
    min_duration: float = 5.0,
    target_max_duration: float = 15.0,
    hard_max_duration: float = 20.0,
) -> list[SemanticSegment]:
    """将转写片段合并为 5-15 秒语义段（硬上限 20 秒）。"""
    out: list[SemanticSegment] = []
    cur = []
    cur_start = None
    for seg in transcript.segments:
        if cur_start is None:
            cur_start = seg.start
        cur.append(seg)
        duration = seg.end - cur_start
        should_cut = False
        if duration >= hard_max_duration:
            should_cut = True
        elif duration >= min_duration and seg.text.strip().endswith(("。", "！", "？", ".", "!", "?")):
            should_cut = True
        elif duration >= target_max_duration:
            should_cut = True
        if should_cut:
            out.append(_pack(cur, len(out)))
            cur = []
            cur_start = None
    if cur:
        out.append(_pack(cur, len(out)))
    logger.info("Built %d semantic segments", len(out))
    return out


def _pack(items, idx: int) -> SemanticSegment:
    return SemanticSegment(
        segment_id=f"s_{idx:03d}",
        start=items[0].start,
        end=items[-1].end,
        text="".join(x.text for x in items),
        source_segment_ids=[x.id for x in items],
    )