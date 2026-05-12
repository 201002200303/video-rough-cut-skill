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
from scripts.plan_edits import plan_edits, plan_edits_v25
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
    """运行 V2 完整处理流水线并返回 SkillOutput。"""
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
        logger.info("【第1步】提取音频 → audio.wav")
        extract_audio(input_video_path, paths["audio"])

        logger.info("【第2步】VAD静音检测 → vad_segments.json")
        vad_data = detect_vad(paths["audio"], paths["vad_segments"])

        logger.info("【第3步】ASR语音转写 → transcript.json")
        transcript = transcribe_audio(
            paths["audio"],
            paths["transcript"],
            provider_name=asr_cfg.get("provider"),
        )

        if bool(tsc.get("enabled", True)):
            logger.info("【第4步】Segment长停顿预切分 → transcript.json")
            transcript = split_transcript_segments_on_word_gaps(
                transcript,
                paths["transcript"],
                word_gap_threshold=float(tsc.get("word_gap_threshold", 0.65)),
                min_segment_duration=float(tsc.get("min_segment_duration", 0.35)),
                min_segment_chars=int(tsc.get("min_segment_chars", 2)),
            )

        logger.info("【第5步】构建语义段 → semantic_segments.json")
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

        logger.info("【第6步】构建语义单元 → utterance_units.json")
        uc = cfg.get("utterance_unit", {})
        utterance_units = build_utterance_units(
            transcript,
            min_duration=float(uc.get("min_duration", 0.35)),
            max_duration=float(uc.get("max_duration", 6.0)),
            word_gap_split_threshold=float(uc.get("word_gap_split_threshold", 0.45)),
        )

        logger.info("【第7步】LLM 语义单元删除检测 → EditDecision + review_needed")
        utterance_units, semantic_edits, review_needed = detect_unit_deletions(
            utterance_units,
            analysis_prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "unit_analysis_correction.md",
            deletion_prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "unit_semantic_dedup.md",
            continuity_prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "deletion_continuity_review.md",
        )
        write_utterance_units(utterance_units, paths["utterance_units"])

        logger.info("【第8步】LLM 局部改口/字级修剪 → EditDecision + review_needed")
        local_repair_edits, review_needed = detect_local_false_start_repairs(
            utterance_units,
            review_needed,
            refine_prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "local_false_start_refine.md",
            continuity_prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "deletion_continuity_review.md",
        )
        semantic_edits.extend(local_repair_edits)

        logger.info("【第9步】LLM 内容清理 → EditDecision + review_needed")
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

        logger.info("【第10步】编辑边界校验 → 解析+对齐 EditDecision")
        semantic_edits, review_needed = resolve_edit_boundaries(
            semantic_edits,
            transcript,
            vad_data,
            review_needed,
        )

        logger.info("【第11步】规则停顿检测 → compress_pause EditDecision")
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

        logger.info("【第12步】编辑决策合并 → edit_decisions.json")
        edit_file = plan_edits(pause_edits, semantic_edits, review_needed, paths["edit_decisions"])

        logger.info("【第13步】时间线重映射 → remapped_transcript.json")
        remapped = remap_timeline(transcript, edit_file, paths["remapped_transcript"])

        logger.info("【第14步】LLM 字幕文本纠错 → remapped_transcript.json")
        remapped = correct_subtitle_text(
            remapped,
            prompt_template_path=Path(__file__).resolve().parent.parent / "prompts" / "subtitle_correction.md",
            reference_units=utterance_units,
        )
        paths["remapped_transcript"].write_text(
            json.dumps(remapped.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info("【第15步】生成转录调试文件 → before/after .md")
        generate_transcript_debug_files(
            before_transcript=transcript,
            after_transcript=remapped,
            edit_decision_file=edit_file,
            before_output_path=paths["transcript_before_edit"],
            after_output_path=paths["transcript_after_edit"],
        )

        logger.info("【第16步】生成 ASS 字幕 → subtitles.ass")
        generate_subtitles(remapped, paths["subtitles"])

        logger.info("【第17步】生成视觉元数据 → visual_metadata.json")
        visual_metadata = generate_visual_metadata(
            remapped,
            paths["visual_metadata"],
            overrides=visual_overrides,
        )

        subtitles_for_render = paths["subtitles"]
        if visual_metadata.enabled:
            logger.info("【第18步】生成视觉叠加层 → visual_overlay.ass + cover.ass")
            subtitles_for_render = generate_packaged_subtitles(
                paths["subtitles"],
                visual_metadata,
                paths["visual_overlay_ass"],
            )
            generate_cover_ass(visual_metadata, paths["cover_ass"])

        logger.info("【第19步】FFmpeg 渲染 → edited_video.mp4")
        render_video(
            input_video_path=input_video_path,
            edit_decisions=[e.model_dump() for e in edit_file.edits],
            subtitles_path=subtitles_for_render,
            output_video_path=paths["edited_video"],
            visual_metadata=visual_metadata,
            cover_ass_path=paths["cover_ass"] if visual_metadata.enabled else None,
            cover_image_path=paths["cover_image"] if visual_metadata.enabled else None,
        )

        logger.info("【第20步】生成剪辑报告 → edit_report.md")
        generate_report(
            input_video_path=input_video_path,
            output_video_path=paths["edited_video"],
            edit_decision_file=edit_file.model_dump(),
            output_path=paths["report"],
        )
    except Exception as exc:
        raise RuntimeError(f"V2 流水线执行失败: {exc}") from exc

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


# ═══════════════════════════════════════════════════════════════════
# V2.5 Pipeline — Semantic Window Patch Pipeline
# ═══════════════════════════════════════════════════════════════════


def run_pipeline_v25(
    input_video_path: Path,
    output_dir: Path,
    mode: str = "standard",
    visual_overrides: dict | None = None,
) -> SkillOutput:
    """V2.5: 全局语义驱动的五段窗口补丁式粗剪流水线。

    核心原则：
    - LLM 负责理解、粗筛、生成候选补丁
    - 代码负责校验、合并、时间轴映射和渲染
    - 纠错结果只作为 display patch，剪辑删除落回原始 source word 时间轴
    """
    load_env()
    cfg = _apply_mode_overrides(reload_config(), mode)
    pc = cfg.get("pause_cut", {})
    tsc = cfg.get("transcript_segment_split", {})
    asr_cfg = cfg.get("asr", {})
    validation_cfg = cfg.get("validation", {})

    input_video_path = Path(input_video_path)
    output_dir = ensure_output_dir(str(output_dir))
    paths = job_output_paths(str(output_dir))
    prompts_dir = Path(__file__).resolve().parent.parent / "prompts"

    try:
        # ════════════════════════════════════════════════════════════
        # 第1-4步：事实层 — 音频提取 → VAD → ASR转写 → 预切分
        # ════════════════════════════════════════════════════════════
        logger.info("=" * 60)
        logger.info("【第1步/共19步】提取音频 → audio.wav")
        logger.info("=" * 60)
        extract_audio(input_video_path, paths["audio"])

        logger.info("=" * 60)
        logger.info("【第2步/共19步】VAD静音检测 → vad_segments.json")
        logger.info("=" * 60)
        vad_data = detect_vad(paths["audio"], paths["vad_segments"])
        logger.info("  [OK] 输出: %s (时长 %.1fs, 语音段 %d)",
                     paths["vad_segments"],
                     vad_data.get("duration", 0.0),
                     len(vad_data.get("speech_segments", [])))

        logger.info("=" * 60)
        logger.info("【第3步/共19步】ASR语音转写 (FunASR/阿里云) → transcript.json")
        logger.info("=" * 60)
        transcript = transcribe_audio(
            paths["audio"],
            paths["transcript"],
            provider_name=asr_cfg.get("provider"),
        )
        logger.info("  [OK] 输出: %s (%d 个segment)",
                     paths["transcript"], len(transcript.segments))

        if bool(tsc.get("enabled", True)):
            logger.info("=" * 60)
            logger.info("【第4步/共19步】Segment长停顿预切分 → transcript.json")
            logger.info("=" * 60)
            before_count = len(transcript.segments)
            transcript = split_transcript_segments_on_word_gaps(
                transcript,
                paths["transcript"],
                word_gap_threshold=float(tsc.get("word_gap_threshold", 0.65)),
                min_segment_duration=float(tsc.get("min_segment_duration", 0.35)),
                min_segment_chars=int(tsc.get("min_segment_chars", 2)),
            )
            logger.info("  [OK] 切分: %d → %d 个segment", before_count, len(transcript.segments))

        # ════════════════════════════════════════════════════════════
        # 第5-6步：构建不可变事实层
        # ════════════════════════════════════════════════════════════
        logger.info("=" * 60)
        logger.info("【第5步/共19步】构建不可变 SourceWord 列表 → source_words.json")
        logger.info("=" * 60)
        from scripts.build_source_words import build_source_words

        source_words = build_source_words(transcript, paths["source_words"])
        provider_count = sum(1 for w in source_words if w.timestamp_source == "provider")
        logger.info("  [OK] 输出: %d 个词 (%d provider, %d estimated)",
                     len(source_words), provider_count, len(source_words) - provider_count)

        logger.info("=" * 60)
        logger.info("【第6步/共19步】构建不可变 SourceSegment 快照 → source_segments.json")
        logger.info("=" * 60)
        from scripts.build_source_segments import build_source_segments

        source_segments = build_source_segments(transcript, source_words, paths["source_segments"])
        logger.info("  [OK] 输出: %d 个segment", len(source_segments))

        # ════════════════════════════════════════════════════════════
        # 第7步：全局语义分析 (LLM)
        # ════════════════════════════════════════════════════════════
        logger.info("=" * 60)
        logger.info("【第7步/共19步】LLM 全局语义分析 → global_context.json")
        logger.info("=" * 60)
        from phases.analyze_global_context import analyze_global_context

        all_text = "\n".join(s.text for s in source_segments)
        global_context = analyze_global_context(
            all_text,
            prompts_dir / "global_context.md",
            paths["global_context"],
        )
        logger.info("  [OK] 话题: %s | 自称: %s | 领域词: %d | 疑似错词: %d",
                     global_context.topic or "(无)",
                     ", ".join(global_context.speaker_aliases) or "(无)",
                     len(global_context.domain_terms),
                     len(global_context.possible_misrecognitions))

        # ════════════════════════════════════════════════════════════
        # 第8步：Segment 问题粗筛 (LLM)
        # ════════════════════════════════════════════════════════════
        logger.info("=" * 60)
        logger.info("【第8步/共19步】LLM Segment 问题粗筛 → segment_issues.json")
        logger.info("=" * 60)
        from phases.screen_segment_issues import screen_segment_issues

        segment_issues = screen_segment_issues(
            source_segments,
            global_context,
            prompts_dir / "segment_issue_screening.md",
            paths["segment_issues"],
        )
        high = sum(1 for i in segment_issues.issues if i.priority == "high")
        med = sum(1 for i in segment_issues.issues if i.priority == "medium")
        low = sum(1 for i in segment_issues.issues if i.priority == "low")
        logger.info("  [OK] 标记: %d 个segment (高:%d 中:%d 低:%d)",
                     len(segment_issues.issues), high, med, low)

        # ════════════════════════════════════════════════════════════
        # 第9步：五段窗口构建 (纯规则)
        # ════════════════════════════════════════════════════════════
        logger.info("=" * 60)
        logger.info("【第9步/共19步】五段窗口构建 → windows.json")
        logger.info("=" * 60)
        from phases.build_windows import build_windows

        window_file = build_windows(source_segments, segment_issues.issues, paths["windows"])
        logger.info("  [OK] 输出: %d 个编辑窗口", len(window_file.windows))

        # ════════════════════════════════════════════════════════════
        # 第10步：窗口 ASR 纠错 + 硬校验 (LLM)
        # ════════════════════════════════════════════════════════════
        logger.info("=" * 60)
        logger.info("【第10步/共19步】LLM 窗口纠错 + 硬校验 → display_patches.json")
        logger.info("=" * 60)
        from phases.correct_window import correct_all_windows

        display_patches, corrected_views = correct_all_windows(
            window_file.windows,
            source_segments,
            source_words,
            global_context,
            prompts_dir / "window_correction.md",
            paths["display_patches"],
        )
        replace_count = sum(1 for p in display_patches if p.type.startswith("replace"))
        insert_count = sum(1 for p in display_patches if p.type == "insert_display")
        delete_display_count = sum(1 for p in display_patches if p.type == "delete_display_noise")
        logger.info("  [OK] 通过硬校验: %d 个字幕补丁 (替换:%d 插入:%d 隐藏:%d)",
                     len(display_patches), replace_count, insert_count, delete_display_count)

        # ════════════════════════════════════════════════════════════
        # 第11步：窗口去重/口误删除 + 硬校验 (LLM)
        # ════════════════════════════════════════════════════════════
        logger.info("=" * 60)
        logger.info("【第11步/共19步】LLM 窗口去重 + 硬校验 → deletion_candidates.json")
        logger.info("=" * 60)
        from phases.dedup_window import dedup_all_windows

        deletion_candidates = dedup_all_windows(
            window_file.windows,
            source_segments,
            source_words,
            corrected_views,
            global_context,
            prompts_dir / "window_dedup.md",
            paths["deletion_candidates"],
        )
        by_type: dict[str, int] = {}
        for dc in deletion_candidates:
            by_type[dc.type] = by_type.get(dc.type, 0) + 1
        logger.info("  [OK] 通过硬校验: %d 个删除候选 %s",
                     len(deletion_candidates),
                     "|".join(f"{k}:{v}" for k, v in sorted(by_type.items())) if by_type else "")

        # ════════════════════════════════════════════════════════════
        # 第12步：停顿检测 (纯规则，不用 LLM)
        # ════════════════════════════════════════════════════════════
        logger.info("=" * 60)
        logger.info("【第12步/共19步】规则停顿检测 → 内部 EditDecision 列表")
        logger.info("=" * 60)
        pause_edits_list = detect_pauses(
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
        post_pauses = detect_post_delete_pauses(
            transcript,
            [*pause_edits_list],
            pause_threshold=float(pc.get("pause_threshold", 0.35)),
            target_pause_duration=float(pc.get("target_pause_duration", 0.15)),
            word_padding=float(pc.get("word_padding", 0.02)),
        )
        pause_edits_list.extend(post_pauses)
        logger.info("  [OK] 检测: %d 个停顿压缩 (其中 %d 个来自删除后暴露)",
                     len(pause_edits_list), len(post_pauses))

        # ════════════════════════════════════════════════════════════
        # 第13步：编辑决策合并
        # ════════════════════════════════════════════════════════════
        logger.info("=" * 60)
        logger.info("【第13步/共19步】编辑决策合并 (删除优先 → 停顿裁剪) → edit_decisions.json")
        logger.info("=" * 60)
        edit_file = plan_edits_v25(
            pause_edits_list,
            deletion_candidates,
            source_words,
            paths["edit_decisions"],
            validation_cfg,
        )
        delete_count = sum(1 for e in edit_file.edits if e.type == "delete")
        pause_count = sum(1 for e in edit_file.edits if e.type == "compress_pause")
        delete_duration = sum(e.end - e.start for e in edit_file.edits if e.type == "delete")
        logger.info("  [OK] 合并: %d 个编辑 (删除:%d/%.1fs 停顿:%d)",
                     len(edit_file.edits), delete_count, delete_duration, pause_count)

        # ════════════════════════════════════════════════════════════
        # 第14步：时间线重映射
        # ════════════════════════════════════════════════════════════
        logger.info("=" * 60)
        logger.info("【第14步/共19步】时间线重映射 → remapped_transcript.json")
        logger.info("=" * 60)
        before_dur = sum(s.end - s.start for s in transcript.segments)
        remapped = remap_timeline(transcript, edit_file, paths["remapped_transcript"])
        after_dur = sum(s.end - s.start for s in remapped.segments)
        logger.info("  [OK] 输出: %.1fs → %.1fs (裁剪 %.1f%%)",
                     before_dur, after_dur,
                     (1 - after_dur / max(before_dur, 0.01)) * 100)

        # ════════════════════════════════════════════════════════════
        # 第15-19步：字幕 → 视觉 → 渲染 → 报告
        # ════════════════════════════════════════════════════════════
        logger.info("=" * 60)
        logger.info("【第15步/共19步】生成 ASS 字幕 (应用 display_patches) → subtitles.ass")
        logger.info("=" * 60)
        generate_subtitles(remapped, paths["subtitles"], display_patches=display_patches)
        logger.info("  [OK] 输出: %s", paths["subtitles"])

        logger.info("=" * 60)
        logger.info("【第16步/共19步】生成视觉元数据 → visual_metadata.json")
        logger.info("=" * 60)
        visual_metadata = generate_visual_metadata(
            remapped,
            paths["visual_metadata"],
            overrides=visual_overrides,
        )
        logger.info("  [OK] 封面标题: %s | 日期: %s | 右上: %s",
                     visual_metadata.cover_title.replace("\n", " "),
                     visual_metadata.date_label or "(自动)",
                     visual_metadata.top_right_label or "(自动)")

        subtitles_for_render = paths["subtitles"]
        if visual_metadata.enabled:
            logger.info("=" * 60)
            logger.info("【第17步/共19步】生成视觉叠加层 → visual_overlay.ass + cover.ass")
            logger.info("=" * 60)
            subtitles_for_render = generate_packaged_subtitles(
                paths["subtitles"],
                visual_metadata,
                paths["visual_overlay_ass"],
            )
            generate_cover_ass(visual_metadata, paths["cover_ass"])
            logger.info("  [OK] 输出: %s | %s", paths["visual_overlay_ass"], paths["cover_ass"])

        logger.info("=" * 60)
        logger.info("【第18步/共19步】FFmpeg 渲染 → edited_video_with_yellow_subtitles.mp4")
        logger.info("=" * 60)
        render_video(
            input_video_path=input_video_path,
            edit_decisions=[e.model_dump() for e in edit_file.edits],
            subtitles_path=subtitles_for_render,
            output_video_path=paths["edited_video"],
            visual_metadata=visual_metadata,
            cover_ass_path=paths["cover_ass"] if visual_metadata.enabled else None,
            cover_image_path=paths["cover_image"] if visual_metadata.enabled else None,
        )
        logger.info("  [OK] 输出: %s", paths["edited_video"])

        logger.info("=" * 60)
        logger.info("【第19步/共19步】生成剪辑报告 → edit_report.md")
        logger.info("=" * 60)
        generate_report(
            input_video_path=input_video_path,
            output_video_path=paths["edited_video"],
            edit_decision_file=edit_file.model_dump(),
            output_path=paths["report"],
            display_patches_count=len(display_patches),
            deletion_candidates_count=len(deletion_candidates),
        )
        logger.info("  [OK] 输出: %s", paths["report"])

    except Exception as exc:
        raise RuntimeError(f"V2.5 流水线执行失败: {exc}") from exc

    logger.info("=" * 60)
    logger.info("V2.5 流水线完成！")
    logger.info("  输入: %s", input_video_path)
    logger.info("  输出: %s", paths["edited_video"])
    logger.info("=" * 60)

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


def main() -> None:
    parser = argparse.ArgumentParser(description="视频粗剪流水线运行器")
    parser.add_argument("--video", type=str, required=True, help="输入视频文件路径")
    parser.add_argument("--output-dir", type=str, required=True, help="输出目录")
    parser.add_argument("--mode", type=str, default="standard", help="处理模式 (standard|conservative|aggressive)")
    parser.add_argument("--pipeline", type=str, default="v2", help="流水线版本 (v2|v25)")
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
    if args.pipeline == "v25":
        logger.info("Running V2.5 pipeline")
        output = run_pipeline_v25(Path(args.video), Path(args.output_dir), args.mode, visual_overrides=visual_overrides)
    else:
        logger.info("Running V2 (legacy) pipeline")
        output = run_pipeline(Path(args.video), Path(args.output_dir), args.mode, visual_overrides=visual_overrides)
    logger.info("Pipeline finished: %s", output.model_dump())
