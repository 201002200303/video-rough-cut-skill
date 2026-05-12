# 视频粗剪 V1 架构文档

## 概述

V1 是一套基于 **segment（片段）** 和 **UtteranceUnit（语义单元）** 的中文口播视频自动粗剪流水线。它以 FunASR 本地语音识别为核心，通过多层 LLM 语义分析和规则引擎，自动检测并删除冗余、口误、重复内容，压缩无意义停顿，最终生成带字幕和视觉包装的精剪视频。

---

## 核心数据模型

### 转录层

| 模型 | 作用 | 关键字段 |
|---|---|---|
| `TranscriptWord` | 字级时间戳 | word, start, end, timestamp_source |
| `TranscriptSegment` | ASR 转写片段 | id, start, end, text, words[] |
| `Transcript` | 完整转写结果 | language, segments[] |

### 语义分析层

| 模型 | 作用 | 关键字段 |
|---|---|---|
| `SemanticSegment` | 5-15s 语义段（多 segment 合并） | segment_id, start, end, text, source_segment_ids[] |
| `UtteranceUnit` | 稳定编号语义单元（0.35–6s） | unit_id, start, end, text, analysis_text, source_segment_ids[], words[] |

### 编辑决策层

| 模型 | 作用 |
|---|---|
| `EditDecision` | 单个编辑决策（delete / compress_pause） |
| `EditDecisionFile` | 所有编辑决策 + review_needed 不确定项 |

### 输入输出层

| 模型 | 作用 |
|---|---|
| `SkillInput` | 流水线输入参数（视频路径、模式、视觉包装等） |
| `SkillOutput` | 流水线输出结果（编辑后视频、字幕、报告等路径） |
| `VisualMetadata` | 封面和叠字视觉包装配置 |

---

## 处理流水线（21 步）

```
┌─────────────────────────────────────────────────────────────┐
│                    V1 Pipeline (21 steps)                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. extract_audio        提取视频音频为 WAV                  │
│  2. detect_vad           FFmpeg silencedetect 静音检测       │
│  3. transcribe_audio     FunASR（主）/ 阿里云 ASR（备）转写  │
│  4. split_transcript_segments  拆分 ASR 段内字间长停顿       │
│                                                             │
│  ┌─── 语义分析（LLM 密集区）──────────────────────────┐     │
│  │                                                     │     │
│  │  5. build_semantic_segments   合并为 5-15s 语义段   │     │
│  │  6. build_utterance_units    构建稳定编号语义单元   │     │
│  │                                                     │     │
│  │  7. detect_unit_deletions    ⭐ 语义去重检测         │     │
│  │     ├─ LLM Call 1: 修正 analysis_text（纠错）       │     │
│  │     ├─ LLM Call 2: 检测可删除单元（去重）           │     │
│  │     └─ LLM Call 3: 连续性复核（每个候选独立调用）   │     │
│  │                                                     │     │
│  │  8. detect_local_false_start  ⭐ 假启动修复          │     │
│  │  9. detect_content_cleanup    ⭐ 内容清理检测        │     │
│  │                                                     │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                             │
│  10. resolve_edit_boundaries   LLM 编辑边界校验与 VAD 吸附  │
│  11. detect_pauses             段间/字间停顿压缩             │
│  12. detect_post_delete_pauses 语义删除后暴露的停顿压缩      │
│  13. plan_edits                合并所有编辑决策              │
│  14. remap_timeline            时间轴重映射                  │
│  15. correct_subtitle_text     ⭐ LLM 字幕文本纠错           │
│  16. generate_transcript_debug 编辑前后对比调试文件          │
│                                                             │
│  ┌─── 输出生成 ───────────────────────────────────────┐     │
│  │                                                     │     │
│  │  17. generate_subtitles        生成 ASS 字幕文件     │     │
│  │  18. generate_visual_metadata  视觉包装元数据        │     │
│  │  19. generate_visual_overlay   封面 ASS + 叠字       │     │
│  │  20. render_video              FFmpeg 渲染输出       │     │
│  │  21. generate_report           Markdown 编辑报告     │     │
│  │                                                     │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 关键模块详解

### 1. ASR 语音识别层 (`providers/`)

```
providers/
├── asr_base.py           # ASR 抽象基类
├── funasr_asr.py         # 本地 FunASR（主要方案）
└── aliyun_asr.py         # 阿里云云端 ASR（备用）
```

- **主方案**：FunASR 本地方案（paraformer-zh 模型），提供字级 provider 时间戳
- **备用方案**：阿里云 ASR（qwen3-asr-flash），支持文件转写接口
- **时间戳来源标记**：每个 `TranscriptWord` 标记 `timestamp_source` 为 `"provider"` 或 `"estimated"`

### 2. LLM 推理层 (`providers/aliyun_qwen.py`)

```
AliyunQwenProvider
├── semantic_dedup()     # 所有 LLM 调用的统一入口
└── _call_qwen()         # DashScope 兼容 API 调用
```

- **单一提供者**：仅阿里云 Qwen（qwen-plus）
- **统一调用方式**：所有 LLM 任务（去重、内容清理、字幕纠错）共享同一个 `semantic_dedup()` 方法
- **JSON-only 输出**：强制 LLM 输出严格 JSON，通过代码围栏剥离处理

### 3. UtteranceUnit 语义单元 (`scripts/build_utterance_units.py`)

这是 V1 架构的核心抽象层：

```
TranscriptSegment（ASR 原始片段）
        ↓ 按 word_gap_split_threshold (0.45s) 切分
        ↓ 合并 0.35-6s 范围的词块
UtteranceUnit（稳定编号语义单元 u-0001, u-0002, ...）
        ↓ 传给 LLM 做语义去重判断
        ↓ LLM 只能返回 unit_id，不能返回任意时间范围
```

**设计意图**：
- 给 LLM 一个稳定、可编号的单元系统
- 限制 LLM 只能全单元删除，避免随意跨边界裁剪
- `analysis_text` 字段允许 LLM 先纠错再用修正文本分析语义

### 4. 语义去重检测 (`scripts/detect_unit_deletions.py`)

**三层 LLM 调用**（V1 最大的性能瓶颈）：

| 步骤 | 函数 | 作用 | LLM 调用次数 |
|---|---|---|---|
| 1 | `_correct_analysis_text()` | 修正 unit 的 ASR 错字，存入 `analysis_text` | 每 chunk 一次 |
| 2 | `_detect_candidates()` | 基于 windowed chunks 识别可删除的 unit | 每 window 一次 |
| 3 | `_review_continuity()` | 删除后检查前后文是否连贯 | **每个候选 unit 一次** |

**窗口策略**：
- 滑窗大小 = `unit_llm_chunk_size`（默认 24）
- 步长 = chunk_size / 2（50% 重叠）
- 避免边界 unit 无法获取足够上下文

### 5. 编辑边界解析 (`scripts/resolve_edit_boundaries.py`)

**安全策略**（V1 的核心防护机制）：

```
LLM 编辑候选
    ↓
是否 provider 时间戳？
    ├─ No  → 若为高置信短 content_cleanup → 放行
    │       否则 → 转入 review_needed（不执行）
    ├─ Yes → VAD 静音边界吸附（±0.35s）
    │        → 字级边界对齐
    │        → 语义删除 padding 扩展
    ↓
安全编辑决策
```

**安全来源标记**：`pause_detector`（规则引擎）直接放行；`semantic_dedup`、`content_cleanup`、`local_false_start_refine`（LLM 来源）必须校验。

### 6. 停顿检测 (`scripts/detect_pauses.py`)

两种停顿检测模式：

- **detect_pauses**（预语义删除）：
  - 段间停顿 > `pause_threshold`（0.22s）→ 压缩
  - 段内字间停顿 > `word_gap_threshold`（0.80s）→ 压缩
  - 句末停顿保护（+0.22s bonus）
  - 首尾静音裁剪

- **detect_post_delete_pauses**（后语义删除）：
  - 语义删除后，相邻保留内容之间的间隙 > 阈值 → 压缩
  - 解决"删了一段话导致前后片段之间产生大空隙"的问题

### 7. 编辑计划合并 (`scripts/plan_edits.py`)

```python
plan_edits(pause_edits, semantic_edits, review_needed)
    ├── _merge_delete_edits()      # 合并重叠的 delete 编辑
    ├── _subtract_deletes_from_pause()  # 删除区间内移除 pause 压缩
    └── _merge_pause_edits()       # 合并重叠的 compress_pause 编辑
```

**优先级规则**：delete > compress_pause（被删除区间的停顿不再压缩）

### 8. Prompt 模板系统 (`prompts/`)

8 个独立 prompt 模板，每个硬编码一个 LLM 任务：

| Prompt 文件 | 用途 | LLM 任务 |
|---|---|---|
| `semantic_dedup.md` | 旧版语义去重 | 检测重复段 |
| `unit_semantic_dedup.md` | 单元级语义去重 | 返回 delete_units[] |
| `unit_analysis_correction.md` | 分析文本纠错 | 修正 analysis_text |
| `deletion_continuity_review.md` | 删除后连续性复核 | 判断前后连贯性 |
| `local_false_start_refine.md` | 假启动修复 | 返回局部编辑 |
| `content_cleanup.md` | 内容清理 | 返回 delete_ranges[] |
| `subtitle_correction.md` | 字幕文本纠错 | 返回修正后 text |

### 9. 字幕纠错 (`scripts/correct_subtitles.py`)

**多级防护**：
- 长度保护：修正后文本长度不超过原文的 1.6 倍
- 相似度保护：修正文本与原文最低相似度 ≥ 0.45
- 数字短语保护：原文中的数字串（如"3.27"、"一千五"）必须保留
- 上下文窗口：带前后各 1 段上下文
- reference_text 参考：可选使用前置语义分析给出的纠错候选

### 10. 配置系统 (`config.default.yaml`)

**三层配置覆盖**：
```
config.default.yaml（默认值）
    ↓
VIDEO_SKILL_CONFIG 环境变量（可选覆盖）
    ↓
--mode standard/conservative/aggressive（模式覆盖）
```

**三种处理模式**：
| 模式 | 停顿检测 | 语义去重 | 适用场景 |
|---|---|---|---|
| `conservative` | 更保守（0.45s 阈值） | 更严格（0.90 相似度） | 需要保留更多原始节奏 |
| `standard` | 默认（0.22s 阈值） | 默认（0.82 相似度） | 通用场景 |
| `aggressive` | 更激进（0.16s 阈值） | 更宽松（0.78 相似度） | 快节奏短视频 |

### 11. 视觉包装系统

```
generate_visual_metadata → visual_metadata.json
generate_visual_overlay  → visual_overlay.ass（右上角标签 + 底部介绍 + 风险提醒）
generate_cover_ass       → cover.ass（封面标题 + 日期 + 小标题）
render_video             → cover.png（可选） → 烧字幕到视频
```

---

## V1 架构特征总结

### 核心设计理念

| 维度 | 特征 |
|---|---|
| **处理粒度** | Segment（ASR 转录片段）为主，UtteranceUnit 为 LLM 分析中介 |
| **语义分析** | 通过 UtteranceUnit 编号系统，LLM 按 unit_id 判断删除 |
| **时间轴** | ASR provider 时间戳 → UtteranceUnit 映射 → EditDecision 时间 → remap |
| **安全机制** | timestamp_source 分级 + VAD 边界吸附 + 编辑边界校验 |
| **LLM 交互** | 每个分析任务独立 prompt + 独立 API 调用 |
| **编辑类型** | delete（语义删除/内容清理）+ compress_pause（停顿压缩） |

### 主要痛点

1. **LLM 调用过多**：语义去重每个 chunk 需要 1 次纠错 + 1 次检测 + N 次连续性复核（N=候选数），是最主要的性能瓶颈
2. **Segment-Unit 双向映射复杂**：UtteranceUnit 从 segment 构建，LLM 返回 unit_id 后又需映射回 segment 的时间范围，链路长且脆弱
3. **固定粒度**：最小操作单元是 UtteranceUnit（0.35-6s），无法做字级精确编辑
4. **Prompt 模板碎片化**：8 个硬编码 prompt 文件，逻辑分散
5. **滑窗策略开销**：50% 重叠的 windowed chunks 导致大量冗余 LLM 调用

### 技术栈

| 层次 | 技术 |
|---|---|
| 语音识别 | FunASR（paraformer-zh + fsmn-vad + ct-punc） |
| LLM | 阿里云 DashScope Qwen-Plus |
| 视频处理 | FFmpeg（filter_complex 策略为主，segment file 为 fallback） |
| 字幕格式 | ASS（Advanced SubStation Alpha） |
| 数据模型 | Pydantic v2 |
| 配置 | YAML + 环境变量覆盖 |

---

## 文件结构一览

```
video_rough_cut_skill/
├── core/
│   ├── __init__.py
│   └── utils.py                  # 日志、配置加载、路径工具
├── providers/
│   ├── __init__.py
│   ├── asr_base.py               # ASR 抽象基类
│   ├── funasr_asr.py             # FunASR 本地 ASR
│   ├── aliyun_asr.py             # 阿里云 ASR
│   ├── llm_base.py               # LLM 抽象基类
│   └── aliyun_qwen.py            # 阿里云 Qwen LLM
├── schemas/
│   ├── __init__.py
│   └── models.py                 # 全部 Pydantic 数据模型
├── scripts/
│   ├── run.py                    # 流水线主入口
│   ├── extract_audio.py          # 音频提取
│   ├── detect_vad.py             # VAD 静音检测
│   ├── transcribe.py             # ASR 转写
│   ├── split_transcript_segments.py   # 拆分长段
│   ├── build_segments.py         # 语义段构建
│   ├── build_utterance_units.py  # 语义单元构建 ⭐
│   ├── detect_unit_deletions.py  # 语义去重检测 ⭐
│   ├── detect_local_false_start_refine.py  # 假启动修复
│   ├── detect_content_cleanup.py # 内容清理 ⭐
│   ├── resolve_edit_boundaries.py # 编辑边界解析
│   ├── detect_pauses.py          # 停顿检测
│   ├── plan_edits.py             # 编辑计划合并
│   ├── remap_timeline.py         # 时间轴重映射
│   ├── correct_subtitles.py      # 字幕文本纠错 ⭐
│   ├── generate_transcript_debug.py  # 调试对比文件
│   ├── generate_subtitles.py     # ASS 字幕生成
│   ├── generate_visual_metadata.py   # 视觉元数据
│   ├── generate_visual_overlay.py    # 封面 + 叠字
│   ├── render_video.py           # FFmpeg 渲染
│   ├── generate_report.py        # Markdown 报告
│   ├── setup_environment.py      # 环境初始化
│   └── test_api_key_speed.py     # API 测速工具
├── prompts/
│   ├── semantic_dedup.md
│   ├── unit_semantic_dedup.md
│   ├── unit_analysis_correction.md
│   ├── deletion_continuity_review.md
│   ├── local_false_start_refine.md
│   ├── content_cleanup.md
│   └── subtitle_correction.md
├── tests/                        # 单元测试
├── tests_tmp/                    # 测试用例快照
├── config.default.yaml           # 默认配置
├── SKILL.md                      # Skill 使用文档
└── requirements.txt              # Python 依赖
```