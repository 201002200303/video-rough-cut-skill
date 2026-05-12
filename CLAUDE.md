# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Chinese spoken-video rough-cutting pipeline (中文口播视频粗剪). Takes a single-speaker Chinese talking-head video and automatically produces a shortened, edited video with burned-in subtitles, cover image, overlays, and disclaimer text. This is a deterministic CLI pipeline, not a web service.

## Common Commands

```bash
# Run the V2 pipeline (legacy)
python -m scripts.run --video "/path/to/input.mp4" --output-dir "/path/to/out" --mode standard

# Run the V2.5 pipeline (Semantic Window Patch)
python -m scripts.run --video "/path/to/input.mp4" --output-dir "/path/to/out" --mode standard --pipeline v25

# Run all tests
pytest

# Run a single test file
pytest tests/test_schemas.py

# Run a single test
pytest tests/test_v25_models.py::TestSourceWord::test_valid_provider_word

# Smoke test (requires real video + API key)
python scripts/dev_smoke_test.py

# Setup environment (Windows)
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1

# Setup environment (Linux)
bash scripts/setup_linux.sh
```

## Architecture

### Pipeline Flow (scripts/run.py)

`run_pipeline()` orchestrates 20 sequential steps. Each step is a standalone module in `scripts/`:

1. **Audio extraction** → FFmpeg 16kHz mono WAV
2. **VAD detection** → FFmpeg silencedetect
3. **ASR transcription** → FunASR (primary, `timestamp_source=provider`) or Aliyun DashScope (fallback, `timestamp_source=estimated`)
4. **Transcript segment splitting** → split ASR segments on long word gaps (configurable threshold, default 0.5s)
5. **Semantic segment building** → merge segments into 5-15s semantic groups for LLM context
6. **Utterance unit building** → split into stable-numbered 0.35-6s units with word boundaries
7. **Unit deletion detection** → LLM finds semantic duplicates and false starts at unit granularity
8. **Local false-start refinement** → LLM does word-level repair when unit-level deletion fails
9. **Content cleanup** → LLM finds off-topic/wasteful content (**disabled by default**; enable via `content_cleanup.enabled: true`)
10. **Edit boundary resolution** → validate LLM-proposed cuts against `timestamp_source` and VAD data
11. **Pause detection** → rule-based pause compression (no LLM)
12. **Post-delete pause detection** → detect pauses that emerge after semantic deletions are applied
13. **Edit planning** → merge overlapping deletes, subtract deletes from pause ranges, produce final edit list
14. **Timeline remap** → rewrite all timestamps after edits
15. **Subtitle correction** → LLM text correction bounded by similarity/length ratio safety checks
16. **Transcript debug generation** → write before/after markdown for human review
17. **ASS subtitle generation** → adaptive font sizing with wrapping and `...` truncation as overflow guard
18. **Visual metadata generation** → auto-generate cover title, date label, top-right label from transcript when not provided
19. **Visual overlay generation** → packaged subtitles ASS + cover ASS with finance-style layout
20. **FFmpeg render** → `filter_complex` strategy (one-pass cut+concat+burn) with segment-file fallback above 80 keep-ranges
21. **Report generation** → markdown edit report

### Key Architectural Principle

**LLM only proposes, scripts verify.** All LLM outputs are semantic candidates. Actual cut boundaries are validated by scripts against `timestamp_source` (provider vs estimated) and VAD alignment. Edits on `estimated` timestamps require higher confidence or are blocked entirely.

### `timestamp_source` Safety Model

- `"provider"` — timestamps from FunASR's model output; trusted for semantic auto-delete
- `"estimated"` — timestamps calculated from word distribution; **not trusted** for broad semantic auto-delete (only high-confidence short content-cleanup cuts allowed when explicitly enabled)
- `boundary_resolver` config section controls the estimated-timestamp safety gates

### Edit Merge Priority (plan_edits.py)

When pause edits and semantic deletes overlap:
1. Overlapping delete ranges are merged into a single delete
2. Delete ranges are subtracted from pause-compress ranges (deletes take priority)
3. Remaining pause-compress ranges are merged if adjacent

### Rendering Strategy (render_video.py)

- **Primary**: `filter_complex` — one FFmpeg invocation cuts, concatenates, and burns subtitles. Fast, single-encode.
- **Fallback**: segment-file rendering — each keep range rendered separately then concatenated. Used when keep-range count exceeds `render.max_filter_complex_segments` (default 80).
- Cover insertion (when `insert_cover_seconds > 0`) adds a second concat pass.

### Three Processing Modes

Defined in `config.default.yaml` under `modes:`:
- `standard` — balanced cutting
- `conservative` — less aggressive, fewer deletions
- `aggressive` — tighter pacing, more deletions

### Config Override Chain

`config.default.yaml` → `VIDEO_SKILL_CONFIG` env var → CLI arguments

After overrides, `_apply_mode_overrides()` deep-merges the mode block into the merged config.

### External Dependencies

- `ffmpeg` and `ffprobe` must be on PATH
- DashScope API key required for LLM calls (set in `.env` as `DASHSCOPE_API_KEY`)
- FunASR models download on first run (paraformer-zh, fsmn-vad, ct-punc)

## Module Layout

- `core/utils.py` — Config loading (YAML + .env + CLI overrides), logging, exception hierarchy (`SkillError`, `ExternalCommandError`, `ProviderError`, `ValidationError`, `ConfigError`), cross-platform command resolution (`resolve_command`), output path catalog
- `providers/` — Abstract base classes (`ASRProvider`, `LLMProvider` + impl: `FunASRProvider` (local, provider timestamps), `AliyunASRProvider` (cloud, estimated timestamps), `AliyunQwenProvider` (DashScope-compatible LLM))
- `schemas/models.py` — All Pydantic v2 models: `TranscriptWord`, `TranscriptSegment`, `Transcript`, `SemanticSegment`, `UtteranceUnit`, `EditDecision`, `EditDecisionFile`, `SkillInput`, `SkillOutput`, `VisualMetadata`
- `prompts/` — LLM prompt templates (Markdown). Active: `unit_semantic_dedup.md`, `unit_analysis_correction.md`, `deletion_continuity_review.md`, `local_false_start_refine.md`, `content_cleanup.md`, `subtitle_correction.md`. Unused/legacy: `semantic_dedup.md`, `local_semantic_dedup.md`
- `scripts/` — Pipeline step modules + `run.py` entry point. Each file is one pipeline step (see flow above).

### V2.5 Architecture (Semantic Window Patch Pipeline)

`run_pipeline_v25()` follows a 19-phase flow with strict separation of concerns:

**Facts Layer (immutable):**
1. extract_audio → 2. detect_vad → 3. transcribe_audio → 4. split_transcript_segments → 5. build_source_words → 6. build_source_segments

**LLM Phases (propose only, code validates):**
7. **Global Context** — LLM extracts topic, speaker aliases, domain terms, likely misrecognitions
8. **Segment Issue Screening** — LLM flags segments needing correction/dedup (coarse scan)
9. **Window Building** — flagged segments expanded to 5-segment windows (target + context), adjacent windows merged

**Correction (display only, no timeline impact):**
10. **Window Correction** — LLM proposes DisplayPatch (replace_display, replace_display_span, insert_display, delete_display_noise) → `validators/correction_validator.py` hard-validates

**Dedup (timeline only):**
11. **Window Dedup** — LLM proposes DeletionCandidate on original source word IDs (using temporary CorrectedView for context only) → `validators/deletion_validator.py` hard-validates

**Rule-based + Rendering (no LLM):**
12. detect_pauses → 13. plan_edits_v25 (deletes > pauses merge) → 14. remap_timeline → 15. generate_subtitles (with display_patches) → 16-19. visual + render

**Key V2.5 differences from V2:**
- `correction_validator.py` + `deletion_validator.py` + `boundary_validator.py` replace LLM review — pure code hard checks
- DisplayPatch only affects subtitles; DeletionCandidate only affects timeline — never mixed
- CorrectedView is temporary, never written back to source transcript
- All LLM deletes must bind to provider-timestamp source words (estimated timestamps rejected)
- `phases/` directory contains V2.5-specific processing modules
- `validators/` directory contains pure-code validators

**New config sections:** `global_context`, `screening`, `window`, `correction`, `validation` (see `config.default.yaml`)

## Testing Patterns

Tests live in `tests/` and use `monkeypatch` to mock the LLM provider and config, returning pre-canned JSON responses. No real API calls are made in tests. When adding a new pipeline step, create a corresponding test file that mocks `LLMProvider.semantic_dedup()`.

Tests construct `Transcript`/`TranscriptSegment`/`TranscriptWord` models directly — no fixtures needed for the core data types. Use Pydantic's `model_validate()` for deserialization round-trip tests.

## Key Data Flow

```
Video → Audio (WAV) → VAD segments → ASR Transcript
  → TranscriptSegments → SemanticSegments → UtteranceUnits
  → EditDecisions (LLM-proposed, script-validated)
  → Timeline remap → ASS subtitles + ASS overlay → Rendered video
```
