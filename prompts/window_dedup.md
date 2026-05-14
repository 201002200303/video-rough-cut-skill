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

## 原始文本（source_text）

以下是窗口内所有 segment 的原始文本，**可能包含 ASR 错字**。全局上下文中的 `canonical_terms` 列出了全文不一致词的标准写法及变体，供你理解语义时参考。你的删除候选必须绑定原始 source word_id。

{{source_text}}

## 任务

**你看到的原始文本可能含 ASR 错字，结合全局上下文中的 `canonical_terms` 理解语义。删除必须返回原始 source word_id。**

你只负责发现以下类型的可删除内容：
- `fast_repetition` — 快速机械重复（如 "这个这个这个地方"）
- `false_start` — 口误/改口/说错后重新起句
- `redundant_restatement` — 语义重述（后一句是前一句的完整展开，保留后一句）
- `incomplete_fragment` — 未完成残句
- `filler_phrase` — 明显口气词片段（如 "嗯"、"呃"、"然后然后"）

**禁止修错字、补字、润色、改写。** 那是纠错阶段的工作。

**重点**：Segments 中标记为 `editable=true` 的段已被上游筛查标记，存在口误/改口/重复的概率远高于普通段。请逐字审查这些段，即使问题较隐晦也应提出候选——硬校验会过滤误报，宁可多提不要漏提。相邻段之间的内容接续关系也要检查。

**判定原则：**
- 如果一句话前后出现相近但不完全相同的两个说法，结合上下文判断：是刻意强调/递进解释，还是脱口而出后立即修正？前者保留，后者删除前一个
- 跨段判定：前一段末尾的表述被后一段重新更完整地起句 → 前一段末尾属于改口，应删除
- 如果删除后 before+after 拼接会产生语法残缺 → 不要删除
- 如果删除范围包含人名、数字、金额、品牌、步骤名 → 不要删除

每个 deletion 必须包含：
- `type`：删除类型
- `word_ids`：**原始 source word ID 列表**（必须能在 words 列表中找到）
- `delete_text_original`：word_ids 对应的原始文本
- `delete_text_corrected_view`：纠错视图中待删除的文本（LLM 根据 global_context.canonical_terms 估算纠错后的拼写，删除候选必须绑定原始 word_id）
- `before_text_corrected_view`：删除范围之前的纠错视图文本
- `after_text_corrected_view`：删除范围之后的纠错视图文本
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
    },
    {
      "type": "false_start",
      "word_ids": ["w-0501", "w-0502"],
      "delete_text_original": "涨价",
      "delete_text_corrected_view": "涨价",
      "before_text_corrected_view": "这个月的",
      "after_text_corrected_view": "价格上调受原材料影响",
      "reason": "先说'涨价'后立即改口为'价格上调'，属于术语纠正型改口",
      "confidence": 0.92
    }
  ]
}
```

只输出 JSON，不要任何额外文本。
