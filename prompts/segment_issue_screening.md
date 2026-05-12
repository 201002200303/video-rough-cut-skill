# Segment 问题粗筛

你正在处理一段中文口播视频。下面是所有 transcript segments 和全局语义上下文。

## 全局上下文

{{global_context}}

## Segments

{{segments_json}}

## 任务

你只负责**粗筛 segment 是否可能存在问题**。
- 不要输出具体修改方案。
- 不要删除内容。
- 如果只是轻微口语表达，不要标记。

常见问题类型：
- `asr_homophone_error` — 同音错词（如"定性晚"应为"定心丸"）
- `speaker_name_error` — 人名/自称错误
- `domain_term_error` — 领域术语识别错误
- `missing_char` — 漏字
- `extra_noise_char` — 多识别的噪声字
- `fast_repetition` — 快速机械重复
- `false_start` — 口误/改口/说错重来
- `semantic_restatement` — 语义重复（后文复述前文）
- `incomplete_fragment` — 未完成残句
- `filler_heavy` — 口气词过多的片段
- `uncertain` — 不确定但需要人工判断

每个 flagged segment 必须给出 `issue_types`、`priority`（high/medium/low）、`evidence`。

## 输出格式

严格输出 JSON：

```json
{
  "issues": [
    {
      "segment_id": "seg-012",
      "issue_types": ["speaker_name_error", "asr_homophone_error"],
      "priority": "high",
      "evidence": "'板也今天认为'应为'板姐今天认为'，上下文多处出现'板姐'作为博主自称"
    },
    {
      "segment_id": "seg-018",
      "issue_types": ["false_start"],
      "priority": "medium",
      "evidence": "前半句'我觉得这个不是'未完成，后文重新起句"
    }
  ]
}
```

只输出 JSON，不要任何额外文本。
