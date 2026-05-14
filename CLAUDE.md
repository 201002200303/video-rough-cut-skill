# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Chinese spoken-video rough-cutting pipeline (中文口播视频粗剪). Takes a single-speaker Chinese talking-head video and automatically produces a shortened, edited video with burned-in subtitles, cover image, overlays, and disclaimer text. This is a deterministic CLI pipeline, not a web service.

## Common Commands

```bash
# Run the pipeline
python -m scripts.run --video "/path/to/input.mp4" --output-dir "/path/to/out" --mode standard

# Run all tests
pytest

# Run a single test file
pytest tests/test_schemas.py

# Run a single test
pytest tests/test_v25_models.py::TestSourceWord::test_valid_provider_word

# Run pipeline core tests (validators + windows + models)
pytest tests/test_v25_models.py tests/test_correction_validator.py tests/test_deletion_validator.py tests/test_boundary_validator.py tests/test_build_windows.py

# Smoke test (requires real video + API key)
python scripts/dev_smoke_test.py

# Setup environment (Windows)
powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1

# Setup environment (Linux)
bash scripts/setup_linux.sh
```

## Architecture

### Pipeline Flow (scripts/run.py)

`run_pipeline()` 是唯一的流水线入口，19 个阶段：

**Facts Layer（不可变事实层）:**
1. extract_audio → 2. detect_vad → 3. transcribe_audio → 4. split_transcript_segments → 5. build_source_words → 6. build_source_segments

**LLM Phases（LLM 只提议，代码校验）:**
7. **Global Context** — LLM 提取话题、说话人、领域词、疑似错词
8. **Segment Issue Screening** — LLM 粗筛有问题的 segment
9. **Window Building** — flagged segment 扩展为五段编辑窗口
10. **Window Correction** — LLM 提出 DisplayPatch → `validators/correction_validator.py` 硬校验
11. **Window Dedup** — LLM 提出 DeletionCandidate → `validators/deletion_validator.py` 硬校验

**Rule-based + Rendering（纯规则，不用 LLM）:**
12. detect_pauses → 13. plan_edits → 14. remap_timeline → 15. generate_subtitles (应用 display_patches) → 16. generate_visual_metadata → 17. generate_visual_overlay → 18. render_video → 19. generate_report

### Key Architectural Principle

**LLM only proposes, scripts verify.** All LLM outputs are semantic candidates. Actual cut boundaries are validated by scripts against `timestamp_source` (provider vs estimated) and VAD alignment. Edits on `estimated` timestamps require higher confidence or are blocked entirely.

### `timestamp_source` Safety Model

- `"provider"` — timestamps from FunASR's model output; trusted for semantic auto-delete
- `"estimated"` — timestamps calculated from word distribution; **not trusted** for broad semantic auto-delete (only high-confidence short content-cleanup cuts allowed when explicitly enabled)
- `boundary_resolver` config section controls the estimated-timestamp safety gates

### Edit Merge Priority (plan_edits.py)

`plan_edits()` 将 `DeletionCandidate` 列表 + pause edits 合并为 `EditDecisionFile`。DeletionCandidate 先转换为带 padding 的 `EditDecision`，然后：
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
- `schemas/models.py` — 所有 Pydantic v2 模型。核心：`SourceWord`, `SourceSegment`, `DisplayPatch`, `DeletionCandidate`, `GlobalContext`, `SegmentIssue`, `Window`, `CorrectionCandidate`, `ValidatedPatchFile`, `ValidatedDeletionFile`；遗留（仍保留）：`TranscriptWord`, `TranscriptSegment`, `Transcript`, `EditDecision`, `EditDecisionFile`, `SkillInput`, `SkillOutput`, `VisualMetadata`
- `prompts/` — LLM prompt templates (Markdown). 5 个活跃 prompt: `global_context.md`, `correction_screening.md`, `dedup_screening.md`, `window_correction.md`, `window_dedup.md`
- `phases/` — LLM 处理阶段：`analyze_global_context.py`, `screen_segment_issues.py`, `build_windows.py`, `correct_window.py`, `dedup_window.py`
- `validators/` — 硬校验器：`correction_validator.py`, `deletion_validator.py`
- `scripts/` — Pipeline 步骤模块 + `run.py` 入口。`plan_edits.py` 合并 V2/V2.5 双版本为单一接口

### 核心架构设计

**DisplayPatch vs DeletionCandidate 严格分离：**
- DisplayPatch（步骤10）只影响字幕展示，不改时间轴
- DeletionCandidate（步骤11）只影响时间轴删除
- 所有 LLM 删除必须绑定 provider 时间戳的 source word（estimated 被硬拒绝）

**硬校验层替代 LLM review：**
- `correction_validator.py` + `deletion_validator.py` 纯代码校验
- 置信度、span 连续性、时间戳来源、删除比例全部硬限位

**新配置段:** `global_context`, `screening`, `window`, `correction`, `validation`（见 `config.default.yaml`）

### Validators（硬校验层）

Two pure-code validators in `validators/` replace LLM review. They hard-enforce safety gates on all LLM output:

- **`correction_validator.py`** — Validates every `CorrectionCandidate` from LLM: word_id existence, from_text matches source words, span continuity, confidence threshold, length ratio bounds (0.4–1.6), insert_display char limit (≤2), text similarity checks for multi-char replacements. Outputs `ValidatedPatchFile` (accepted/rejected).
- **`deletion_validator.py`** — Validates every `DeletionCandidate`: word_id existence, span continuity, **all words must have `timestamp_source=provider`** (estimated timestamps hard-rejected), confidence threshold, max single-delete duration, cumulative delete ratio cap (default 22% of total video). Outputs `ValidatedDeletionFile`. Also provides `resolve_deletion_times()` to convert word_ids → (start, end) with padding.

### Docs and Design References

- `docs/architecture-v1.md` — Full V1 architecture with data model tables, pipeline flow, and design rationale.
- `docs/pipeline-v2-design.md` — V2 redesign proposal: global context → word-level correction → word-level dedup → pause cut.
- `dev_log.md` — Chronological development log (P1–P14) documenting key decisions, parameter tuning, and real-world test results.

## Testing Patterns

Tests live in `tests/` and use `monkeypatch` to mock the LLM provider and config, returning pre-canned JSON responses. No real API calls are made in tests. When adding a new pipeline step, create a corresponding test file that mocks `LLMProvider.semantic_dedup()`.

Tests construct `Transcript`/`TranscriptSegment`/`TranscriptWord` models directly — no fixtures needed for the core data types. Use Pydantic's `model_validate()` for deserialization round-trip tests.

## Key Data Flow

```
Video → Audio (WAV) → VAD segments → ASR Transcript
  → SourceWords (不可变) → SourceSegments (不可变)
  → GlobalContext → SegmentIssues → Windows
  → DisplayPatches (字幕纠错) + DeletionCandidates (时间轴删除)
  → EditDecisions (硬校验通过) → Timeline remap
  → ASS subtitles (应用 display_patches) + ASS overlay → Rendered video
```

## Agent skills

### Issue tracker

Issues 使用 GitHub Issues (`github.com/201002200303/video-rough-cut-skill`)，通过 `gh` CLI 操作。详见 `docs/agents/issue-tracker.md`。

### Triage labels

使用默认标签名：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文仓库。`CONTEXT.md` + `docs/adr/` 位于仓库根目录（尚未创建，由 `grill-with-docs` 按需生成）。详见 `docs/agents/domain.md`。
