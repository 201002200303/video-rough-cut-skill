# 窗口内 ASR 纠错

你正在处理一个 5-segment 编辑窗口。你**只负责 ASR 纠错候选**。

## 窗口 ID

{{window_id}}

## 全局上下文

{{global_context}}

若全局上下文中含 `canonical_terms`，纠错时优先将 segment 里属于 `variants` 的写法统一为对应 `canonical`；替换须仍满足下文对 `replace_display`、`replace_display_span` 的读音约束（同音/近音），禁止借「统一术语」做语义重写。可与 `canonical_speaker_name` 同时参考：自称仍以 `canonical_speaker_name` 为准，领域/实体用词以 `canonical_terms` 为准。

## Segments（带编辑权限）

{{segments_json}}

## Words（word_id → char/time/segment）

{{words_json}}

## 任务

**你只负责 ASR 纠错候选。**
- 禁止去重、删口误、润色、改写。
- 禁止输出删除候选（那是另一个阶段的工作）。
- **禁止语义重写**：替换后的文本必须与原文字音相同或相近，不能把原文改写成完全不同读音的词。

### 同音/近音判断标准

提出纠错候选时，必须严格遵循以下判别流程。**音箱先于词典**：先判断读音是否接近，再判断语义。

**第一步**：怀疑当前词是错的（语境不自然）。
**第二步**：想一个候选词，写出两个词的完整拼音。
**第三步**：对照以下 6 类近音模式，判断两个拼音是否属于同一类。
**第四步**：只有通过第三步，且候选词放入上下文确实更好时，才输出候选。

如果第三步不通过（拼音差很远），即使候选词语义再好，也**绝对不能输出**。

**ASR 同音/近音模式共 6 类：**

| 类型 | 说明 | 示例词对 |
|------|------|----------|
| 完全同音 | 拼音完全相同（含声调） | 骨/股(gǔ)、巳/四(sì)、受/售(shòu)、西/吸(xī) |
| 声调不同 | 声母韵母一致，仅声调差异 | 几片(piàn)→几篇(piān)、信号码(mǎ)→信号吗(ma) |
| 声母近音 | 韵母相同，声母为常见混淆对 | 少年(shào)→数年(shù)、听(tīng)→提醒(tíxǐng) |
| 韵母近音 | 声母相同，韵母为常见混淆对 | 定性(xìng)→定心(xīn)、碳酸铝(lǚ)→碳酸锂(lǐ) |
| n/l 不分 | 南方口音常见混淆 | 十年(nián)→十连(lián)、牛肉→流肉 |
| 平翘舌不分 | zh/ch/sh 与 z/c/s 混淆 | 资产(zī)→质产(zhì)、找到(zhǎo)→早到(zǎo) |

若全局上下文中含 `canonical_terms`，变体统一时也须通过上述同音/近音模式校验，禁止借"统一术语"做语义重写。

允许的纠错类型：
- `replace_display` — 单字替换（如 "也" → "姐"）。单字替换无限制
- `replace_display_span` — 多字同音/近音替换（如 "定性晚" → "定心丸"）。**多字替换必须与原词读音相近**，不同读音的词不能替换
- `insert_display` — 补漏字（如 ASR 漏了一个"姐"字）。每次最多补 1-2 个字
- `delete_display_noise` — 隐藏**单个**多余的 ASR 幻听汉字（"今天大盘呢"中多出的"呢"）。只能标记**一个汉字**，不能多字

每个 correction 必须包含：
- `word_ids`：原始 source word ID 列表（**必须能在上面的 words 列表中找到**）
- `from_text`：word_ids 对应的原始文本（**必须等于 words 中对应 char 的拼接**）
- `to_text`：修正后的显示文本
- `confidence`：0.0-1.0
- `evidence`：纠错证据（必须引用 local_context 或 global_context）
- `type`：纠正类型

**说话人自称统一**：如果全局上下文中有 `canonical_speaker_name` 且置信度 >0.8，全文所有自称变体统一替换为该标准自称。这是高优先级纠错任务。

**输出原则**：有合理纠错嫌疑就输出候选，不要等"确定无疑"。后续有硬校验兜底，会过滤不合理的候选。宁可多提被拒，不要漏提。

重要约束：
- `from_text` 必须能由 word_ids 在原始输入中精确拼出
- `insert_display` 必须指定 `after_word_id`（在哪个 word 之后插入）
- `insert_display` 不参与时间轴，只影响字幕显示

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
