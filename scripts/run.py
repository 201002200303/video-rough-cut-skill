"""流水线运行器：执行完整 MVP 流水线。"""

import argparse
import json
from pathlib import Path

from core.utils import setup_logger
from core.utils import ensure_output_dir, job_output_paths
from core.utils import load_env, reload_config
from schemas.models import SkillOutput
from scripts.extract_audio import extract_audio
from scripts.detect_vad import detect_vad
from scripts.transcribe import transcribe_audio
from scripts.detect_pauses import detect_pauses
from scripts.detect_pauses import detect_post_delete_pauses
from scripts.split_transcript_segments import split_transcript_segments_on_word_gaps
from scripts.build_segments import build_semantic_segments
from scripts.build_utterance_units import build_utterance_units, write_utterance_units
from scripts.detect_unit_deletions import detect_unit_deletions
from scripts.detect_local_false_start_refine import detect_local_false_start_repairs
from scripts.detect_content_cleanup import detect_content_cleanup
from scripts.resolve_edit_boundaries import resolve_edit_boundaries
from scripts.plan_edits import plan_edits
from scripts.remap_timeline import remap_timeline
from scripts.correct_subtitles import correct_subtitle_text
from scripts.generate_transcript_debug import generate_transcript_debug_files
from scripts.generate_subtitles import generate_subtitles
from scripts.generate_visual_metadata import generate_visual_metadata
from scripts.generate_visual_metadata import load_visual_overrides
from scripts.generate_visual_overlay import generate_cover_ass
from scripts.generate_visual_overlay import generate_packaged_subtitles
from scripts.render_video import render_video
from scripts.generate_report import generate_report

logger = setup_logger(__name__)


def run_pipeline(
    input_video_path: Path,
    output_dir: Path,
    mode: str = "standard",
    visual_overrides: dict | None = None,
) -> SkillOutput:
    """运行完整处理流水线并返回 SkillOutput。"""
    load_env()
    cfg = _apply_mode_overrides(reload_config(), mode)
    pc = cfg.get("pause_cut", {})
    dc = cfg.get("dedup", {})
    cc = cfg.get("content_cleanup", {})
    sc = cfg.get("semantic_segment", {})
    tsc = cfg.get("transcript_segment_split", {})
    asr_cfg = cfg.get("asr", {})
    input_video_path = Path(input_video_path)
    output_dir = ensure_output_dir(str(output_dir))
    paths = job_output_paths(str(output_dir))
    try:
        logger.info("Step extract_audio")
        extract_audio(input_video_path, paths["audio"])

        logger.info("Step detect_vad")
        vad_data = detect_vad(paths["audio"], paths["vad_segments"])

        logger.info("Step transcribe_audio")
        transcript = transcribe_audio(
            paths["audio"],
            paths["transcript"],
            provider_name=asr_cfg.get("provider"),
        )

        if bool(tsc.get("enabled", True)):
            logger.info("Step split_transcript_segments")
            transcript = split_transcript_segments_on_word_gaps(
                transcript,
                paths["transcript"],
                word_gap_threshold=float(tsc.get("word_gap_threshold", 0.65)),
                min_segment_duration=float(tsc.get("min_segment_duration", 0.35)),
                min_segment_chars=int(tsc.get("min_segment_chars", 2)),
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

        logger.info("Step build_utterance_units")
        uc = cfg.get("utterance_unit", {})
        utterance_units = build_utterance_units(
            transcript,
            min_duration=float(uc.get("min_duration", 0.35)),
            max_duration=float(uc.get("max_duration", 6.0)),
            word_gap_split_threshold=float(uc.get("word_gap_split_threshold", 0.45)),
        )

        logger.info("Step detect_unit_deletions")
        utterance_units, semantic_edits, review_needed = detect_unit_deletions(
            utterance_units,
            analysis_prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "unit_analysis_correction.md",
            deletion_prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "unit_semantic_dedup.md",
            continuity_prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "deletion_continuity_review.md",
        )
        write_utterance_units(utterance_units, paths["utterance_units"])

        logger.info("Step detect_local_false_start_repairs")
        local_repair_edits, review_needed = detect_local_false_start_repairs(
            utterance_units,
            review_needed,
            refine_prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "local_false_start_refine.md",
            continuity_prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "deletion_continuity_review.md",
        )
        semantic_edits.extend(local_repair_edits)

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

        logger.info("Step detect_pauses")
        pause_edits = detect_pauses(
            transcript,
            pause_threshold=float(pc.get("pause_threshold", 0.35)),
            target_pause_duration=float(pc.get("target_pause_duration", 0.15)),
            word_padding=float(pc.get("word_padding", 0.02)),
            keep_sentence_boundary_pause=bool(pc.get("keep_sentence_boundary_pause", True)),
            sentence_boundary_pause_bonus=float(pc.get("sentence_boundary_pause_bonus", 0.3)),
            use_word_gaps=bool(pc.get("use_word_gaps", True)),
            word_gap_threshold=float(pc.get("word_gap_threshold", pc.get("pause_threshold", 0.35))),
            trim_edge_silence=bool(pc.get("trim_edge_silence", True)),
            media_duration=float(vad_data.get("duration", 0.0) or 0.0),
        )
        pause_edits.extend(
            detect_post_delete_pauses(
                transcript,
                [*pause_edits, *semantic_edits],
                pause_threshold=float(pc.get("pause_threshold", 0.35)),
                target_pause_duration=float(pc.get("target_pause_duration", 0.15)),
                word_padding=float(pc.get("word_padding", 0.02)),
            )
        )

        logger.info("Step plan_edits")
        edit_file = plan_edits(pause_edits, semantic_edits, review_needed, paths["edit_decisions"])

        logger.info("Step remap_timeline")
        remapped = remap_timeline(transcript, edit_file, paths["remapped_transcript"])

        logger.info("Step correct_subtitle_text")
        remapped = correct_subtitle_text(
            remapped,
            prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "subtitle_correction.md",
            reference_units=utterance_units,
        )
        paths["remapped_transcript"].write_text(
            json.dumps(remapped.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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

        logger.info("Step generate_visual_metadata")
        visual_metadata = generate_visual_metadata(
            remapped,
            paths["visual_metadata"],
            overrides=visual_overrides,
        )

        subtitles_for_render = paths["subtitles"]
        if visual_metadata.enabled:
            logger.info("Step generate_visual_overlay")
            subtitles_for_render = generate_packaged_subtitles(
                paths["subtitles"],
                visual_metadata,
                paths["visual_overlay_ass"],
            )
            generate_cover_ass(visual_metadata, paths["cover_ass"])

        logger.info("Step render_video")
        render_video(
            input_video_path=input_video_path,
            edit_decisions=[e.model_dump() for e in edit_file.edits],
            subtitles_path=subtitles_for_render,
            output_video_path=paths["edited_video"],
            visual_metadata=visual_metadata,
            cover_ass_path=paths["cover_ass"] if visual_metadata.enabled else None,
            cover_image_path=paths["cover_image"] if visual_metadata.enabled else None,
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
        visual_metadata_path=str(paths["visual_metadata"]),
        visual_overlay_ass_path=str(paths["visual_overlay_ass"]) if visual_metadata.enabled else None,
        cover_image_path=str(paths["cover_image"])
        if visual_metadata.enabled and (visual_metadata.generate_cover or visual_metadata.insert_cover_seconds > 0)
        else None,
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
    parser.add_argument("--visual-metadata", type=str, default=None, help="Optional JSON file with cover and overlay fields")
    parser.add_argument("--cover-title", type=str, default=None, help="Large cover title; use \\n for two lines")
    parser.add_argument("--date-label", type=str, default=None, help="Cover date label, for example 2026.3.27")
    parser.add_argument("--cover-subtitle", type=str, default=None, help="Cover subtitle shown near date")
    parser.add_argument("--top-right-label", type=str, default=None, help="Top-right in-video label")
    parser.add_argument("--person-intro", type=str, default=None, help="Bottom person introduction line")
    parser.add_argument("--insert-cover-seconds", type=float, default=None, help="Optional still-cover intro duration")
    args = parser.parse_args()
    visual_overrides = load_visual_overrides(
        Path(args.visual_metadata) if args.visual_metadata else None,
        {
            "cover_title": args.cover_title,
            "date_label": args.date_label,
            "cover_subtitle": args.cover_subtitle,
            "top_right_label": args.top_right_label,
            "person_intro": args.person_intro,
            "insert_cover_seconds": args.insert_cover_seconds,
        },
    )
    output = run_pipeline(Path(args.video), Path(args.output_dir), args.mode, visual_overrides=visual_overrides)
    logger.info("Pipeline finished: %s", output.model_dump())


if __name__ == "__main__":
    main()
