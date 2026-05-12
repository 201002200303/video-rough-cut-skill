# 窗口内去重/口误删除

你正在处理一个 5-segment 编辑窗口。你**只负责发现应该删除的视频片段**。

## 窗口 ID

{{window_id}}

## 全局上下文

{{global_context}}

## Segments（带编辑权限）

{{segments_json}}

## Words（word_id → char/time/segment）

{{words_json}}

## 纠错后的文本（corrected_view）

以下是应用了 ASR 纠错后的文本，**仅供你理解语义**。你的删除候选必须绑定原始 source word_id。

{{corrected_text}}

## 任务

**你看到 corrected_view 是为了理解语义，但删除必须返回原始 source word_id。**

你只负责发现以下类型的可删除内容：
- `fast_repetition` — 快速机械重复（如 "这个这个这个地方"）
- `false_start` — 口误/改口/说错后重新起句
- `redundant_restatement` — 语义重述（后一句是前一句的完整展开，保留后一句）
- `incomplete_fragment` — 未完成残句
- `filler_phrase` — 明显口气词片段（如 "嗯"、"呃"、"然后然后"）

**禁止修错字、补字、润色、改写。** 那是纠错阶段的工作。

**保守原则：**
- 如果重复是强调、承接、解释递进 → 不要删除
- 如果删除后 before+after 拼接会产生语法残缺 → 不要删除
- 如果删除范围包含人名、数字、金额、品牌、步骤名 → 不要删除
- 宁可漏删，不要误删

每个 deletion 必须包含：
- `type`：删除类型
- `word_ids`：**原始 source word ID 列表**（必须能在 words 列表中找到）
- `delete_text_original`：word_ids 对应的原始文本
- `delete_text_corrected_view`：word_ids 在 corrected_view 中对应的文本
- `before_text_corrected_view`：删除范围之前的上下文
- `after_text_corrected_view`：删除范围之后的上下文
- `reason`：删除理由
- `confidence`：0.0-1.0

## 输出格式

```json
{
  "deletions": [
    {
      "type": "false_start",
      "word_ids": ["w-0301", "w-0302", "w-0303", "w-0304"],
      "delete_text_original": "我觉得这个不是",
      "delete_text_corrected_view": "我觉得这个不是",
      "before_text_corrected_view": "这里大家一定要注意",
      "after_text_corrected_view": "我们应该先看墙面有没有空鼓",
      "reason": "前半句是未完成表达，后文重新完整起句",
      "confidence": 0.90
    },
    {
      "type": "fast_repetition",
      "word_ids": ["w-0410", "w-0411"],
      "delete_text_original": "这个这个",
      "delete_text_corrected_view": "这个这个",
      "before_text_corrected_view": "我们来看",
      "after_text_corrected_view": "这个地方要注意",
      "reason": "快速机械重复'这个'两次，删除一次不影响理解",
      "confidence": 0.94
    }
  ]
}
```

只输出 JSON，不要任何额外文本。
