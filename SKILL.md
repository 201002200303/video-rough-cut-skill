---
name: video-rough-cut
description: Chinese spoken-video rough cutting with FunASR timestamps, pause compression, configurable semantic cleanup, subtitle correction, faster FFmpeg rendering, adaptive ASS subtitles, and finance-style cover/overlay packaging. Use when Codex needs to turn a local Chinese talking-head video into a shortened edited video with subtitles, a generated cover image, top-right label, bottom person intro, and fixed risk reminders.
---

# Video Rough Cut

## Scope

- Do Chinese spoken-video rough cutting with pause compression, semantic deletion candidates, subtitle correction, ASS subtitle burn-in, cover generation, and fixed visual overlays.
- Do not run an HTTP service, manage a SQLite job queue, make multi-speaker editorial decisions, or let LLMs execute FFmpeg commands.
- Use FFmpeg only through deterministic scripts in this skill.

## Environment Setup

Before running the pipeline for a non-technical user, prefer the automatic setup scripts instead of asking the user to install FFmpeg or edit PATH manually.

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```

Linux:

```bash
bash scripts/setup_linux.sh
```

These scripts create `.venv`, install Python dependencies, create `.env` from `.env.example` when needed, install/check FFmpeg, and on Windows add the discovered FFmpeg `bin` directory to the current user's PATH. If the Windows PATH is changed, tell the user to reopen PowerShell/CMD/Codex terminal before running the pipeline.

After setup, run the pipeline with the virtualenv Python explicitly. This avoids accidentally using Conda/base Python or another system Python.

Windows:

```powershell
.\.venv\Scripts\python.exe -m scripts.run --video "D:\data\test.mp4" --output-dir "D:\data\out" --mode standard
```

Linux:

```bash
./.venv/bin/python -m scripts.run --video "/data/test.mp4" --output-dir "/data/out" --mode standard
```

Before a real run, verify required runtime pieces:

```powershell
.\.venv\Scripts\python.exe -c "from core.utils import resolve_command; print(resolve_command('ffmpeg')); print(resolve_command('ffprobe'))"
```

```bash
./.venv/bin/python -c "from core.utils import resolve_command; print(resolve_command('ffmpeg')); print(resolve_command('ffprobe'))"
```

Also check `.env` has a real `DASHSCOPE_API_KEY`. If it still contains the placeholder value, ask the user for the key or pause before semantic/LLM steps.

If only FFmpeg/PATH repair is needed, skip Python dependency installation:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -SkipPythonDeps
```

```bash
bash scripts/setup_linux.sh --skip-python-deps
```

## Ask First

Before running the pipeline, ask the user for any visual packaging preferences that are not already provided:

- cover title, date label, and cover subtitle
- top-right in-video label
- bottom person intro line
- whether to insert the generated cover as a short video intro
- whether speed or semantic cleanup quality matters more for this run

If the user does not provide visual text, continue with defaults. The skill will generate a short title from transcript text when possible, use today's date, create a `MMDD 收评` top-right label, and use the configured fixed person intro and risk reminders.

For faster runs, keep `content_cleanup.enabled=false` unless the user asks for content cleanup review. `dedup.enabled=false` can skip semantic deletion entirely when speed matters more than cleanup depth.

Do not rewrite the configured risk reminders unless the user explicitly asks. For finance videos, keep the reminder block visible by default.

Long pauses inside one ASR segment are split before semantic analysis. This turns a false start followed by a restart into separate numbered segments, so the LLM can decide whether the earlier fragment should be deleted.

## Input

Minimal input:

```json
{
  "input_video_path": "D:/data/test.mp4",
  "output_dir": "D:/data/out",
  "mode": "standard"
}
```

Optional visual metadata can be passed as a JSON file or CLI flags:

```json
{
  "cover_title": "今天是\n反转信号？",
  "date_label": "2026.3.27",
  "cover_subtitle": "看盘笔记",
  "top_right_label": "0327 收评",
  "person_intro": "九方智投 投顾（谈军 登记编号：A0740625030028）",
  "insert_cover_seconds": 0.0
}
```

## Run

```powershell
.\.venv\Scripts\python.exe -m scripts.run --video "D:\data\test.mp4" --output-dir "D:\data\out" --mode standard
```

With explicit visual packaging:

```powershell
.\.venv\Scripts\python.exe -m scripts.run --video "D:\data\test.mp4" --output-dir "D:\data\out" --mode standard --cover-title "今天是\n反转信号？" --date-label "2026.3.27" --top-right-label "0327 收评"
```

## Output

- `edited_video_with_yellow_subtitles.mp4`
- `cover.png`
- `visual_metadata.json`
- `visual_overlay.ass`
- `cover.ass`
- `transcript.json`
- `semantic_segments.json`
- `utterance_units.json`
- `edit_decisions.json`
- `remapped_transcript.json`
- `subtitles.ass`
- `edit_report.md`

## Visual Layout

- Main spoken subtitles are white with black outline and are raised above the bottom disclosure block.
- Cover title is bold yellow with black outline, centered near the upper half of the frame.
- Cover date and cover subtitle are yellow with black outline in the lower-left area.
- Top-right label is yellow with black outline.
- Bottom intro and three reminder lines are fixed white text with black outline.
- Overlay text is automatically wrapped, downscaled, and truncated with `...` only as a final overflow guard.
- Tune sizes, colors, and positions in `config.default.yaml` under `subtitle` and `visual_overlay`.

## Performance

- Rendering defaults to `render.strategy=filter_complex`, which cuts, concatenates, and burns subtitles in one FFmpeg encode when the number of kept ranges is within `max_filter_complex_segments`.
- The old segment-file render path remains as a fallback for very complex edit lists.
- Cover image generation adds two small FFmpeg image steps. Inserting the cover as a video intro adds another concat pass and should be used only when desired.
- Content cleanup LLM calls are disabled by default; semantic deletion and subtitle correction remain configurable.

## Pipeline

1. `extract_audio`
2. `detect_vad`
3. `transcribe_audio`
4. `split_transcript_segments`
5. `build_semantic_segments`
6. `build_utterance_units`
7. `detect_unit_deletions`
8. `detect_content_cleanup`
9. `resolve_edit_boundaries`
10. `detect_pauses`
11. `plan_edits`
12. `remap_timeline`
13. `correct_subtitle_text`
14. `generate_subtitles`
15. `generate_visual_metadata`
16. `generate_visual_overlay`
17. `render_video`
18. `generate_report`

## Requirements

- `ffmpeg` and `ffprobe` on `PATH`
- `funasr`, `torch`, and `torchaudio` for the primary local timestamp ASR path
- `DASHSCOPE_API_KEY` for LLM semantic analysis and Aliyun fallback
- Main settings in `config.default.yaml`; override with `VIDEO_SKILL_CONFIG`

## Safety

- ASR does not decide what to delete.
- LLM only proposes semantic candidates and subtitle text corrections.
- `timestamp_source="estimated"` is not trusted for broad semantic auto-delete.
- Risk reminders are fixed configuration text unless the user explicitly changes them.
