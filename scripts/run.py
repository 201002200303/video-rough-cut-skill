"""流水线运行器：执行完整 MVP 流水线。"""

import argparse
import json
from pathlib import Path

from core.logging import setup_logger
from core.paths import ensure_output_dir, job_output_paths
from core.config import load_env, reload_config
from schemas.skill_output import SkillOutput
from scripts.extract_audio import extract_audio
from scripts.detect_vad import detect_vad
from scripts.transcribe import transcribe_audio
from scripts.detect_pauses import detect_pauses
from scripts.build_segments import build_semantic_segments
from scripts.detect_repetition import detect_repetition
from scripts.detect_content_cleanup import detect_content_cleanup
from scripts.resolve_edit_boundaries import resolve_edit_boundaries
from scripts.plan_edits import plan_edits
from scripts.remap_timeline import remap_timeline
from scripts.generate_transcript_debug import generate_transcript_debug_files
from scripts.generate_subtitles import generate_subtitles
from scripts.render_video import render_video
from scripts.generate_report import generate_report

logger = setup_logger(__name__)


def run_pipeline(input_video_path: Path, output_dir: Path, mode: str = "standard") -> SkillOutput:
    """运行完整处理流水线并返回 SkillOutput。"""
    load_env()
    cfg = _apply_mode_overrides(reload_config(), mode)
    pc = cfg.get("pause_cut", {})
    dc = cfg.get("dedup", {})
    cc = cfg.get("content_cleanup", {})
    sc = cfg.get("semantic_segment", {})
    input_video_path = Path(input_video_path)
    output_dir = ensure_output_dir(str(output_dir))
    paths = job_output_paths(str(output_dir))
    try:
        logger.info("Step extract_audio")
        extract_audio(input_video_path, paths["audio"])

        logger.info("Step detect_vad")
        vad_data = detect_vad(paths["audio"], paths["vad_segments"])

        logger.info("Step transcribe_audio")
        transcript = transcribe_audio(paths["audio"], paths["transcript"], provider_name="aliyun")

        logger.info("Step detect_pauses")
        pause_edits = detect_pauses(
            transcript,
            pause_threshold=float(pc.get("pause_threshold", 0.35)),
            target_pause_duration=float(pc.get("target_pause_duration", 0.15)),
            word_padding=float(pc.get("word_padding", 0.02)),
            keep_sentence_boundary_pause=bool(pc.get("keep_sentence_boundary_pause", True)),
            sentence_boundary_pause_bonus=float(pc.get("sentence_boundary_pause_bonus", 0.3)),
            use_word_gaps=bool(pc.get("use_word_gaps", True)),
        )

        logger.info("Step build_semantic_segments")
        semantic_segments = build_semantic_segments(
            transcript,
            min_duration=float(sc.get("min_duration", 5.0)),
            target_max_duration=float(sc.get("target_max_duration", 15.0)),
            hard_max_duration=float(sc.get("hard_max_duration", 20.0)),
        )
        paths["semantic_segments"].write_text(
            json.dumps([s.model_dump() for s in semantic_segments], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info("Step detect_repetition")
        semantic_edits, review_needed = detect_repetition(
            [s.model_dump() for s in semantic_segments],
            prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "semantic_dedup.md",
            semantic_window_seconds=float(dc.get("semantic_window_seconds", 90.0)),
            min_confidence_to_delete=float(dc.get("similarity_threshold", 0.85)),
            context_window_segments=int(dc.get("context_window_segments", 3)),
            max_segment_chars=int(dc.get("max_segment_chars", 500)),
            review_on_uncertain=bool(dc.get("review_on_uncertain", True)),
            max_auto_delete_duration=float(dc.get("max_auto_delete_duration", 4.0)),
        )

        logger.info("Step detect_content_cleanup")
        cleanup_edits, cleanup_review_needed = detect_content_cleanup(
            transcript,
            prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "content_cleanup.md",
            min_confidence_to_delete=float(cc.get("min_confidence_to_delete", 0.92)),
            max_segment_chars=int(cc.get("max_segment_chars", 300)),
            review_on_uncertain=bool(cc.get("review_on_uncertain", True)),
            max_auto_delete_duration=float(cc.get("max_auto_delete_duration", 3.0)),
            boundary_guard=float(cc.get("boundary_guard", 0.25)),
            auto_delete_enabled=bool(cc.get("auto_delete_enabled", False)),
        )
        semantic_edits.extend(cleanup_edits)
        review_needed.extend(cleanup_review_needed)

        logger.info("Step resolve_edit_boundaries")
        semantic_edits, review_needed = resolve_edit_boundaries(
            semantic_edits,
            transcript,
            vad_data,
            review_needed,
        )

        logger.info("Step plan_edits")
        edit_file = plan_edits(pause_edits, semantic_edits, review_needed, paths["edit_decisions"])

        logger.info("Step remap_timeline")
        remapped = remap_timeline(transcript, edit_file, paths["remapped_transcript"])

        logger.info("Step generate_transcript_debug")
        generate_transcript_debug_files(
            before_transcript=transcript,
            after_transcript=remapped,
            edit_decision_file=edit_file,
            before_output_path=paths["transcript_before_edit"],
            after_output_path=paths["transcript_after_edit"],
        )

        logger.info("Step generate_subtitles")
        generate_subtitles(remapped, paths["subtitles"])

        logger.info("Step render_video")
        render_video(
            input_video_path=input_video_path,
            edit_decisions=[e.model_dump() for e in edit_file.edits],
            subtitles_path=paths["subtitles"],
            output_video_path=paths["edited_video"],
        )

        logger.info("Step generate_report")
        generate_report(
            input_video_path=input_video_path,
            output_video_path=paths["edited_video"],
            edit_decision_file=edit_file.model_dump(),
            output_path=paths["report"],
        )
    except Exception as exc:
        raise RuntimeError(f"pipeline step failed: {exc}") from exc

    return SkillOutput(
        edited_video_path=str(paths["edited_video"]),
        transcript_path=str(paths["transcript"]),
        edit_decisions_path=str(paths["edit_decisions"]),
        subtitles_path=str(paths["subtitles"]),
        report_path=str(paths["report"]),
    )


def _apply_mode_overrides(cfg: dict, mode: str) -> dict:
    if mode not in ("standard", "conservative", "aggressive"):
        raise ValueError("mode must be 'standard', 'conservative', or 'aggressive'")
    merged = dict(cfg)
    overrides = cfg.get("modes", {}).get(mode, {})
    _deep_merge_copy(merged, overrides)
    return merged


def _deep_merge_copy(base: dict, overlay: dict) -> None:
    for key, value in overlay.items():
        if isinstance(base.get(key), dict) and isinstance(value, dict):
            _deep_merge_copy(base[key], value)
        else:
            base[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description="视频粗剪流水线运行器")
    parser.add_argument("--video", type=str, required=True, help="输入视频文件路径")
    parser.add_argument("--output-dir", type=str, required=True, help="输出目录")
    parser.add_argument("--mode", type=str, default="standard", help="处理模式")
    args = parser.parse_args()
    output = run_pipeline(Path(args.video), Path(args.output_dir), args.mode)
    logger.info("Pipeline finished: %s", output.model_dump())


if __name__ == "__main__":
    main()