# 窗口内 ASR 纠错

你正在处理一个 5-segment 编辑窗口。你**只负责 ASR 纠错候选**。

## 窗口 ID

{{window_id}}

## 全局上下文

{{global_context}}

## Segments（带编辑权限）

{{segments_json}}

## Words（word_id → char/time/segment）

{{words_json}}

## 任务

**你只负责 ASR 纠错候选。**
- 禁止去重、删口误、润色、改写。
- 禁止输出删除候选（那是另一个阶段的工作）。

允许的纠错类型：
- `replace_display` — 单字替换（如 "也" → "姐"）
- `replace_display_span` — 多字替换（如 "定性晚" → "定心丸"）
- `insert_display` — 补漏字（如 ASR 漏了一个"姐"字）
- `delete_display_noise` — 隐藏明显的噪声字/ASR幻听字（仅影响字幕显示，不删除视频片段）

每个 correction 必须包含：
- `word_ids`：原始 source word ID 列表（**必须能在上面的 words 列表中找到**）
- `from_text`：word_ids 对应的原始文本（**必须等于 words 中对应 char 的拼接**）
- `to_text`：修正后的显示文本
- `confidence`：0.0-1.0
- `evidence`：纠错证据（必须引用 local_context 或 global_context）
- `type`：纠正类型

重要约束：
- `from_text` 必须能由 word_ids 在原始输入中精确拼出
- `insert_display` 必须指定 `after_word_id`（在哪个 word 之后插入）
- `insert_display` 不参与时间轴，只影响字幕显示
- 没有高置信证据就不要输出

## 输出格式

```json
{
  "corrections": [
    {
      "type": "replace_display",
      "word_ids": ["w-0122"],
      "from_text": "也",
      "to_text": "姐",
      "confidence": 0.93,
      "evidence": {
        "local_context": "'板也今天认为'语义不通",
        "global_context": "全文存在'板姐'作为博主自称",
        "category": "speaker_name_error"
      }
    },
    {
      "type": "replace_display_span",
      "word_ids": ["w-0180", "w-0181", "w-0182"],
      "from_text": "定性晚",
      "to_text": "定心丸",
      "confidence": 0.91,
      "evidence": {
        "local_context": "该句语义为安抚用户，'定心丸'是常见固定表达",
        "category": "asr_homophone_error"
      }
    },
    {
      "type": "insert_display",
      "after_word_id": "w-0250",
      "from_text": "",
      "to_text": "姐",
      "confidence": 0.87,
      "evidence": {
        "local_context": "'板今天认为'应为'板姐今天认为'，漏了一个自称词"
      }
    }
  ]
}
```

只输出 JSON，不要任何额外文本。
