# 视频粗剪 Pipeline V2 重构设计

## 概述

V2 重构核心思路：**全局语义先行 → 字级精确纠错 → 字级去重删口误 → 口气剪辑**。

解决 V1 的核心问题：
- ASR 错别字（尤其是博主自称、人称代词、领域术语）在全文上下文中不一致
- 纠错和去重两步分离不清晰，analysis_text 生命周期混乱
- 口误检测依赖自然语言关键词路由，不稳定
- 两次 ASR 纠错（unit_analysis_correction + subtitle_correction）重复且可能矛盾

---

## 完整 Pipeline 流程

```
输入: 原始视频 (.mp4)
     │
     ▼
┌─────────────────────────────────────────────┐
│ Step 0: 音频提取 + VAD + FunASR 转写         │
│   extract_audio → detect_vad → transcribe    │
│   产物: audio.wav, vad_segments.json,        │
│         transcript.json（含 provider words）  │
└─────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────┐
│ Step 1: Segment 预切分                        │
│   split_transcript_segments                  │
│   按字间停顿 > 0.65s 切分 segment             │
│   产物: transcript.json（含切分后的 segments） │
└─────────────────────────────────────────────┘
     │
     ▼
╔═════════════════════════════════════════════╗
║           Phase A: 全局语义分析               ║
╠═════════════════════════════════════════════╣
║ Step A1: 整篇 transcript → LLM              ║
║   输入: 全部 segments 的纯文本拼接            ║
║   输出: global_context.json                 ║
║                                             ║
║ Step A2: 如有不确定性 → 通过 Skill API 提问   ║
║   用户回答 → 回填 global_context.resolved    ║
║   （仅此阶段可提问，后续步骤不再交互）         ║
╚═════════════════════════════════════════════╝
     │
     ▼
╔═════════════════════════════════════════════╗
║         Phase B: 字级纠错（Word Correction）  ║
╠═════════════════════════════════════════════╣
║ Step B1: 粗筛 — 哪些 segment 需要纠错         ║
║   输入: 全部 segments + global_context       ║
║   输出: 标记的 segment_id 列表               ║
║                                             ║
║ Step B2: 细粒度纠错（3-segment 窗口）          ║
║   输入: target + before + after segment     ║
║         + 字级编号 + global_context          ║
║   输出: corrections[] (replace/delete/insert) ║
║                                             ║
║ Step B3: Review                              ║
║   应用 corrections → 检查语义通畅性           ║
║   通过 → 提交；失败 → 重试（最多2轮）         ║
║   仍失败 → 标记 human_review                 ║
║                                             ║
║ Step B4: 重新编号                            ║
║   应用所有 corrections，重新生成连续 word ID  ║
║   产物: transcript_corrected.json            ║
╚═════════════════════════════════════════════╝
     │
     ▼
╔═════════════════════════════════════════════╗
║      Phase C: 去重 & 口误删除（Dedup）        ║
╠═════════════════════════════════════════════╣
║ Step C1: 粗筛 — 哪些 segment 区域有重复       ║
║   输入: transcript_corrected + global_context║
║   输出: 标记的 segment_id 列表               ║
║                                             ║
║ Step C2: 细粒度删除（3-segment 窗口）          ║
║   输入: target + before + after segment     ║
║         + 字级编号（基于纠正后文本）           ║
║         + global_context                    ║
║   输出: deletions[] (word_id 范围删除)        ║
║                                             ║
║ Step C3: Review                              ║
║   应用 deletions → 检查语义通畅性             ║
║   通过 → 提交；失败 → 重试（最多2轮）         ║
║   仍失败 → 标记 human_review                 ║
║                                             ║
║ Step C4: 应用删除，生成干净字幕                ║
║   产物: transcript_clean.json                ║
║         此时字幕已完成，不需要后续再纠错       ║
╚═════════════════════════════════════════════╝
     │
     ▼
╔═════════════════════════════════════════════╗
║         Phase D: 口气 & 停顿剪辑             ║
╠═════════════════════════════════════════════╣
║ Step D1: detect_pauses                      ║
║   基于 transcript_clean 的 provider words    ║
║   检测字间/段间长停顿 → compress_pause edits  ║
║                                             ║
║ Step D2: detect_post_delete_pauses          ║
║   检测删除后暴露的间隙                       ║
║                                             ║
║ Step D3: resolve_edit_boundaries            ║
║   VAD 吸附 + provider 校验 + padding         ║
╚═════════════════════════════════════════════╝
     │
     ▼
┌─────────────────────────────────────────────┐
│ Step 5: plan_edits + remap_timeline          │
│   合并所有 EditDecision → 重映射时间轴        │
│   产物: edit_decisions.json,                │
│         remapped_transcript.json            │
└─────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────┐
│ Step 6: 渲染（字幕 + 封面 + 最终视频）         │
│   generate_subtitles → generate_visual_*     │
│   → render_video → generate_report          │
└─────────────────────────────────────────────┘
```

---

## Phase A: 全局语义分析

### A1: 全局语义提取

**输入**：全部 segments 的拼接文本（带 segment_id 标注）

```
[seg-001] 大家好我是板姐
[seg-002] 今天板姐给大家聊聊装修
[seg-003] 装修里面有很多坑
...
```

**LLM 输出 schema**：

```json
{
  "speakers": {
    "count": 1,
    "primary": {
      "self_reference_names": [
        {
          "observed_form": "板姐",
          "likely_correct": null,
          "confidence": "uncertain",
          "occurrence_segment_ids": ["seg-001", "seg-002", "seg-008"],
          "context_clue": "博主人称自称，多次出现，可能是人名/昵称"
        }
      ],
      "self_reference_pronouns": ["我", "我们"],
      "role_guess": "装修/家居类知识博主"
    }
  },
  "topic": {
    "primary": "旧房改造省钱攻略",
    "domain_keywords": [
      {"term": "腻子", "context": "墙面处理材料"},
      {"term": "美缝", "context": "瓷砖填缝工艺"},
      {"term": "阴阳角", "context": "墙面转角处理"}
    ]
  },
  "narrative_style": "单人讲解，面向装修小白，语气亲切口语化",
  "dialogue_flag": false,
  "uncertainties": [
    {
      "uncertainty_id": "u-001",
      "type": "speaker_name",
      "observed_forms": ["板姐", "栏姐"],
      "segment_ids": ["seg-001", "seg-002", "seg-008"],
      "question_for_user": "视频中博主自称什么名字？听到几种可能：",
      "options": [
        {"label": "樊姐（人名）", "value": "樊姐"},
        {"label": "板姐（板材行业相关）", "value": "板姐"},
        {"label": "其他（请说明）", "value": "__custom__"}
      ]
    }
  ]
}
```

### A2: 用户交互（仅此阶段）

当 `uncertainties` 非空时：

1. Pipeline 暂停，通过 Skill API 返回问题列表给 Agent
2. Agent 展示给用户（带选项，一键选择）
3. 用户回答后写入 `global_context.resolved`

```json
{
  "resolved": [
    {
      "uncertainty_id": "u-001",
      "answer": "樊姐",
      "resolution": "博主自称'樊姐'，为人物昵称"
    }
  ]
}
```

**设计原则**：
- 每次最多 3~5 个问题，避免用户疲劳
- 全部带选项，减少打字
- 确定的事直接写，不确定才问
- 后续 Phase B/C/D 不再提问

---

## Phase B: 字级纠错

### 核心约束

| 操作 | 含义 | 时间戳 | 说明 |
|---|---|---|---|
| `replace` | word_id → new_char | 继承原 word 时间戳 | 1:1 替换，如 "板"→"樊" |
| `delete` | 删除 word_id | 时间戳随之删除 | 口吃/多余字 |
| `insert` | 在某 word_id 之后插入 new_char | 继承前一个 word 的时间戳 | ASR 漏字，如 "板"→"板姐" |

**关键规则**：
- insert 只能补充 ASR 漏掉的字，不能新增语义
- insert 的字继承被插入位置相邻 word 的 timestamp_source
- 所有操作都在**原始 transcript 的 word 列表**上进行，操作后重新编号

### B1: 粗筛

**输入**：全部 segments（每个 segment 的 text）+ global_context

**LLM 任务**：快速扫描，标记哪些 segment 明显有错别字/主语不一致需要修正。

**输出**：

```json
{
  "flagged_segment_ids": ["seg-001", "seg-005", "seg-012"],
  "summary": "seg-001 博主自称'板姐'可能应为'樊姐'；seg-005 '的/地/得'混用；seg-012 领域术语'阴阳角'疑似识别错误"
}
```

### B2: 细粒度纠错（3-segment 窗口）

**窗口合并规则**：相邻的被标记 segment 合并为一个窗口。例如 seg-002, seg-003, seg-004, seg-005 都被标记 → 合并为一个窗口 seg-001+[seg-002~005]+seg-006。

**输入格式**（字级编号，跨 segment 连续）：

```
[global_context] 如上

[seg-001] 大家好我是板姐
  w0:大  w1:家  w2:好  w3:我  w4:是  w5:板  w6:姐
[seg-002] 今天板姐给大家聊聊装修
  w7:今  w8:天  w9:板  w10:姐  w11:给  w12:大  w13:家  w14:聊  w15:聊  w16:装  w17:修
[seg-003] 装修里面有很多坑
  w18:装  w19:修  w20:里  w21:面  w22:有  w23:很  w24:多  w25:坑
```

**LLM 输出**：

```json
{
  "corrections": [
    {"word_id": 5, "action": "replace", "new_char": "樊", "reason": "博主自称，参考 global_context 中用户确认为'樊姐'"},
    {"word_id": 9, "action": "replace", "new_char": "樊", "reason": "同上，全文主语统一"},
    {"word_id": 15, "action": "delete", "reason": "口吃重复字'聊聊'→'聊'"},
    {"word_id": 16, "action": "replace", "new_char": "装", "reason": "上下文语义，应为'装修'而非'装潢'，维持原有'装'字"},
    {"word_id": 7, "action": "insert", "new_char": "姐", "reason": "ASR漏字，原句'今天板今天给大家'应为'今天板姐今天给大家'，在w7'今'后补'姐'"}
  ]
}
```

**insert 的时间戳处理**：

```
原始 w6:姐(start=1.2, end=1.4) → w7:今(start=1.6, end=1.8)
在 w6 之后 insert "姐":
  w6:姐(start=1.2, end=1.4) 
  w6a:姐(start=1.4, end=1.4, timestamp_source="estimated")
  w7:今(start=1.6, end=1.8)
```

insert 的字 `start=end=前一个word.end`，`timestamp_source="estimated"`。在后续 remap 时作为估计值处理。

### B3: Review 机制

**流程**：

```
corrections 产出
    │
    ▼
在内存中应用 corrections → 生成 modified_text
    │
    ▼
Review LLM: 
  输入: original_text + modified_text + global_context
  输出: {pass: bool, issues: [...]}
    │
┌───┴───┐
▼       ▼
pass   fail
│       │
▼       ▼
提交   将 issues 注入纠错 LLM 上下文 → 重新生成 corrections
        │
        ▼
      再次 review（最多 2 轮）
        │
   ┌────┴────┐
   ▼         ▼
  pass    仍失败 → 标记 human_review
```

**Review 输出格式（结构化）**：

```json
{
  "pass": false,
  "issues": [
    {
      "word_id": 15,
      "type": "over_correction",
      "problem": "'聊聊'在口播语境中常见，删掉第二个'聊'后变成'聊装修'，语义虽通但改变了口播风格"
    },
    {
      "word_id": 7,
      "type": "wrong_position",
      "problem": "原文'今天板姐给大家'，insert'姐'应在'板'之后而非'今'之后"
    }
  ]
}
```

**失败重试时的上下文构造**：

```
# System
你上一轮的修正有 2 处被 review 驳回：
- word_id=15: '聊聊'在口播语境中常见，删掉后改变了口播风格。如非必要，保留口语化表达。
- word_id=7: insert 位置错误，'姐'应在'板'后面。

请根据驳回意见重新输出修正 JSON。无问题的项可保留。

# User
（和第一次相同的输入）
```

### B4: 重新编号

应用所有通过 review 的 corrections 后，重新生成连续 word ID：

```
修正前: w0:大 w1:家 w2:好 w3:我 w4:是 w5:板 w6:姐 w7:今 w8:天 w9:板 ...
                              ↓ replace w5:板→樊
                              ↓ insert "姐" after w5 (ASR漏字被补回，实际w5后已有w6:姐，此处跳过)
修正后: w0:大 w1:家 w2:好 w3:我 w4:是 w5:樊 w6:姐 w7:今 w8:天 w9:樊 ...
                              ↓ 重新编号
        w0:大 w1:家 w2:好 w3:我 w4:是 w5:樊 w6:姐 w7:今 w8:天 w9:樊 ...
```

产物：`transcript_corrected.json`，包含修正后的 word 列表和时间戳。

---

## Phase C: 去重 & 口误删除

### 核心约束

- 仅支持 `delete` 操作（删除 word_id 范围）
- 不修改字符内容（纠错已在 Phase B 完成）
- 输入文本是 Phase B 纠正后的干净文本

### C1: 粗筛

**输入**：transcript_corrected + global_context

**LLM 任务**：扫描整篇，标记哪些 segment 区域存在语义重复、false start、残句。

**输出**：

```json
{
  "flagged_segment_ids": ["seg-004", "seg-005", "seg-009"],
  "summary": "seg-004~005 句尾'装修'和句首'装修'重复；seg-009 '那个那个...'为口误false start"
}
```

### C2: 细粒度删除（3-segment 窗口）

**输入格式**（基于 Phase B 纠正后的字级编号）：

```
[global_context] 如上

[seg-003] 今天樊姐给大家聊装修
  w0:今 w1:天 w2:樊 w3:姐 w4:给 w5:大 w6:家 w7:聊 w8:装 w9:修
[seg-004] 装修里面有很多坑
  w10:装 w11:修 w12:里 w13:面 w14:有 w15:很 w16:多 w17:坑
[seg-005] 那个那个那个我们今天来讲
  w18:那 w19:个 w20:那 w21:个 w22:那 w23:个 w24:我 w25:们 w26:今 w27:天 w28:来 w29:讲
```

**LLM 输出**：

```json
{
  "deletions": [
    {"word_ids": [10, 11], "type": "chained_repetition", "reason": "句尾'装修'+句首'装修'，链式重复，删除句首的重复"},
    {"word_ids": [18, 19, 20, 21, 22, 23], "type": "false_start", "reason": "'那个那个那个'为典型口误false start，删除后语义从'我们今天来讲'开始"}
  ]
}
```

`type` 枚举值：`chained_repetition`（链式重复）、`false_start`（口误）、`redundant_restatement`（多余重述）、`incomplete_fragment`（残句）

### C3: Review 机制

与 Phase B3 相同结构。Review LLM 检查删除后 `before + after` 是否语义连贯。

```json
{
  "pass": false,
  "issues": [
    {
      "word_ids": [10, 11],
      "type": "broken_connection",
      "problem": "删除'装修'后，seg-003结尾'聊'+seg-004开头'里面'变成'聊里面'，不通顺"
    }
  ]
}
```

### C4: 应用删除

产出 `transcript_clean.json`——**这是最终字幕的直接来源，不需要后续再做字幕纠错**。

---

## Phase D: 口气 & 停顿剪辑

基于 `transcript_clean.json`，复用现有逻辑：

### D1: detect_pauses

- 检测 segment 间间隔、word 间间隔
- 超过阈值 → `compress_pause` edit
- 句末标点（。？！）给予额外停顿宽容

### D2: detect_post_delete_pauses

- 检测 Phase C 删除后暴露的间隙
- 对这些间隙生成额外的 `compress_pause` edit

### D3: resolve_edit_boundaries

- VAD 吸附：将 edit 边界吸附到最近的 VAD 静音段边界
- Provider 校验：确保 edit 不切割 provider 时间戳覆盖的 word
- Padding：在 delete edit 前后留少量保护间隔

---

## Step 5-6: 剪辑脚本生成 & 渲染

与现有逻辑基本一致：

```
plan_edits → remap_timeline → generate_subtitles → 
generate_visual_* → render_video → generate_report
```

关键差异：
- `remap_timeline` 的输入是 `transcript_clean.json`（而非原始 transcript）
- 字幕直接使用 `transcript_clean.json` 中的 text，**不再经过 subtitle_correction**
- `generate_subtitles` 输出 `.ass` 字幕时，时间戳已经在 Phase C 的删除和 Phase D 的 pause 压缩中被正确处理

---

## 数据流总览

```
transcript.json (FunASR 原始)
    │
    ▼ Phase A
global_context.json
    │
    ▼ Phase B (在内存中操作 word 列表)
transcript_corrected.json (纠错后，word 列表修改)
    │
    ▼ Phase C (在内存中操作 word 列表)
transcript_clean.json (去重后，word 列表删除)
    │
    ▼ Phase D
edit_decisions.json (pause edits + delete edits + boundary adjustments)
    │
    ▼ Step 5
remapped_transcript.json (最终时间轴)
    │
    ▼ Step 6
subtitles.ass + cover.png + edited_video.mp4
```

---

## 待删除的旧代码

以下 V1 脚本/文件在新 pipeline 中不再使用：

| 文件 | 原因 |
|---|---|
| `scripts/build_utterance_units.py` | 不再需要 utterance 中间抽象层 |
| `scripts/build_segments.py` | 不再需要 semantic_segments |
| `scripts/detect_unit_deletions.py` | 被 Phase B+C 替代 |
| `scripts/detect_local_false_start_refine.py` | 被 Phase C 替代 |
| `scripts/detect_content_cleanup.py` | 被 Phase B+C 替代 |
| `scripts/detect_repetition.py` | 已被废弃（V1 也未使用） |
| `scripts/correct_subtitles.py` | 不再需要二次字幕纠错 |
| `prompts/unit_analysis_correction.md` | 被 Phase B prompt 替代 |
| `prompts/unit_semantic_dedup.md` | 被 Phase C prompt 替代 |
| `prompts/deletion_continuity_review.md` | 被统一 Review prompt 替代 |
| `prompts/local_false_start_refine.md` | 被 Phase C prompt 替代 |
| `prompts/local_semantic_dedup.md` | 已被废弃（V1 也未使用） |
| `prompts/semantic_dedup.md` | 已被废弃（V1 也未使用） |
| `prompts/subtitle_correction.md` | 不再需要二次字幕纠错 |
| `prompts/content_cleanup.md` | 被 Phase B+C 替代 |

---

## 新增文件

| 文件 | 用途 |
|---|---|
| `scripts/analyze_global_context.py` | Phase A：全局语义分析 + 用户交互 |
| `scripts/correct_transcript_words.py` | Phase B：字级纠错（粗筛+细粒度+review） |
| `scripts/dedup_transcript_words.py` | Phase C：去重&口误删除（粗筛+细粒度+review） |
| `prompts/global_context.md` | Phase A 的 prompt 模板 |
| `prompts/word_correction.md` | Phase B 纠错 prompt 模板 |
| `prompts/word_correction_review.md` | Phase B review prompt 模板 |
| `prompts/word_dedup.md` | Phase C 去重 prompt 模板 |
| `prompts/word_dedup_review.md` | Phase C review prompt 模板 |
| `schemas/models.py` | 新增 `GlobalContext`、`Correction`、`Deletion` 等 model |

---

## 新增数据模型

```python
class GlobalContext(BaseModel):
    """Phase A 产出：全文语义上下文"""
    speakers: SpeakerProfile
    topic: TopicInfo
    narrative_style: str
    dialogue_flag: bool = False
    uncertainties: list[Uncertainty] = []
    resolved: list[Resolution] = []

class SpeakerProfile(BaseModel):
    count: int
    primary: PrimarySpeaker

class PrimarySpeaker(BaseModel):
    self_reference_names: list[SelfReferenceName] = []
    self_reference_pronouns: list[str] = []
    role_guess: str = ""

class SelfReferenceName(BaseModel):
    observed_form: str
    likely_correct: str | None = None
    confidence: str  # "certain" | "uncertain"
    occurrence_segment_ids: list[str] = []
    context_clue: str = ""

class TopicInfo(BaseModel):
    primary: str
    domain_keywords: list[DomainKeyword] = []

class DomainKeyword(BaseModel):
    term: str
    context: str = ""

class Uncertainty(BaseModel):
    uncertainty_id: str
    type: str  # "speaker_name" | "domain_term" | "other"
    observed_forms: list[str] = []
    segment_ids: list[str] = []
    question_for_user: str
    options: list[UncertaintyOption] = []

class UncertaintyOption(BaseModel):
    label: str
    value: str

class Resolution(BaseModel):
    uncertainty_id: str
    answer: str
    resolution: str = ""

class WordCorrection(BaseModel):
    """Phase B 产出：单个纠错操作"""
    word_id: int
    action: str  # "replace" | "delete" | "insert"
    new_char: str = ""  # replace/insert 时使用
    reason: str = ""

class WordDeletion(BaseModel):
    """Phase C 产出：单个删除操作"""
    word_ids: list[int]  # 可删除单个字或连续多个字
    type: str  # "chained_repetition" | "false_start" | "redundant_restatement" | "incomplete_fragment"
    reason: str = ""

class ReviewResult(BaseModel):
    """Review 步骤统一输出"""
    pass_: bool = Field(alias="pass")
    issues: list[ReviewIssue] = []

class ReviewIssue(BaseModel):
    word_id: int | None = None  # Phase B 用
    word_ids: list[int] | None = None  # Phase C 用
    type: str  # "over_correction" | "wrong_position" | "broken_connection" | ...
    problem: str = ""
```

---

## 配置变更

`config.default.yaml` 需要新增：

```yaml
# Phase A: 全局语义分析
global_context:
  enabled: true
  model: "qwen-plus"         # 需要较强推理能力

# Phase B: 字级纠错
word_correction:
  enabled: true
  model: "qwen-plus"
  max_review_rounds: 2       # review 失败后最多重试轮数
  min_confidence: 0.85       # replace 操作的最低置信度

# Phase C: 去重 & 口误删除
word_dedup:
  enabled: true
  model: "qwen-plus"
  max_review_rounds: 2
  min_confidence: 0.85
  max_delete_ratio: 0.30     # 单窗口最多删除 30% 的字

# 以下配置项不再需要（可移除或标记 deprecated）
# - utterance_unit
# - dedup (旧版)
# - content_cleanup
# - semantic_segment
```