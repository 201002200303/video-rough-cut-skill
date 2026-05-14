# 口误/去重粗筛

你只负责**粗筛 segment 中可能的口误、改口、重复、残句**。你看到的是原始转写文本（含 ASR 错字），结合全局上下文理解语义。

## 全局上下文

{{global_context}}

## Segments

{{segments_json}}

## 任务

**你只找口误和冗余内容，不找 ASR 错字。纠错是另一个阶段的工作。**

允许标记的问题类型：
- `false_start` — 口误/改口/说错后重新起句。包括：
  - **句法改口**：前半句未完成，重新起句
  - **术语纠正**：先说了一个词A，立刻换成近义词/同义词/更精准的领域词B。A和B语义相近但不完全相同，不是机械重复
  - **跨段改口**：前一段末尾的表述被后一段重新更完整地起句
- `fast_repetition` — 快速机械重复（同一个词连续说两次）
- `redundant_restatement` — 语义重复（后文用不同措辞复述前文，保留后一次）
- `incomplete_fragment` — 未完成残句（句子只有开头没有结尾）
- `filler_phrase` — 明显口气词片段（如"嗯""呃""然后然后"）
- `uncertain` — 无法确定但需要人工判断

**不能标记的类型（这些是纠错阶段的工作）：**
- `asr_homophone_error` — 同音错字
- `speaker_name_error` — 人名错
- `missing_char` — 漏字
- `extra_noise_char` — 幻听噪声字

**注意**：文本中可能包含 ASR 错字，不要因为这些错字影响你对内容结构的判断。全局上下文的 `canonical_terms` 列出了全文不一致词的标准写法及其变体，可以帮助你理解可能的错词。ASR 错字导致的表面重复不要标记，但真实的口误碎片（说话人真的说了"假期"然后改口说"一大批"）要标记为 `false_start`。

每个 flagged segment 必须给出 `issue_types`、`priority`（high/medium/low）、`evidence`。

## 输出格式

严格输出 JSON：

```json
{
  "issues": [
    {
      "segment_id": "seg-018",
      "issue_types": ["false_start"],
      "priority": "medium",
      "evidence": "前半句'我觉得这个不是'未完成，后文重新起句"
    },
    {
      "segment_id": "seg-025",
      "issue_types": ["false_start"],
      "priority": "high",
      "evidence": "先说'涨价'后立即改口为'价格上调'，属于术语纠正型改口"
    },
    {
      "segment_id": "seg-040",
      "issue_types": ["fast_repetition"],
      "priority": "medium",
      "evidence": "连续两个'这个'，属于机械重复"
    }
  ]
}
```

只输出 JSON，不要任何额外文本。