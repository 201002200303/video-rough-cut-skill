# 开发日志

## P1 基础流水线（2026-04-28）

- 建立视频粗剪 pipeline 和核心数据结构。
- 增加 FFmpeg 音频抽取、停顿检测、语义分段、剪辑决策、时间轴重映射、字幕生成、视频渲染和报告输出。

## P2 DashScope 真实调用（2026-04-28）

- 增加 DashScope LLM provider，用于语义去重和内容清理候选判断。
- 增加 `qwen3-asr-flash` chat ASR 路径。
- 确认该路径只返回识别文本，不返回真实 begin/end/word 时间戳，因此代码生成的 word timestamps 只能标记为 `estimated`。

## P3 安全边界和调试产物（2026-04-29）

- 增加基于 FFmpeg `silencedetect` 的 VAD。
- transcript word 增加 `timestamp_source: provider|estimated`。
- 增加边界解析器，避免基于估算时间戳的语义删除直接自动执行。
- 增加 `transcript_before_edit.md` 和 `transcript_after_edit.md`，便于人工核对剪辑前后时间轴。

## P4 Qwen-ASR FileTrans 支持（2026-04-29）

- 增加 `qwen3-asr-flash-filetrans` 异步任务路径。
- 支持解析 `transcripts[].sentences[].words[].begin_time/end_time/text/punctuation` 为真实 provider 时间戳。
- 使用当前真实 key 测试时返回 `Model.AccessDenied`，因此 FileTrans 代码保留，但默认关闭。

## P5 渲染兼容和默认值调整（2026-04-29）

- 增加 H.264 profile、level、movflags、CRF、preset、pixel format 等可配置项。
- 收紧暂停剪辑和内容清理默认值。
- `content_cleanup.auto_delete_enabled` 默认保持 `false`，语义清理候选进入 review，不直接删除。

## P6 架构精简和 FunASR 主路径（2026-05-06）

- 删除 `api/` 目录，移除 FastAPI、SQLite、Worker 层。skill 入口统一为本地脚本。
- 合并 `core/config.py`、`exceptions.py`、`logging.py`、`paths.py` 到 `core/utils.py`。
- 合并多个 schema 文件到 `schemas/models.py`，删除 API-only Job 模型和未使用 Subtitle 模型。
- 删除未被 pipeline 引用的 `prompts/continuity_check.md`。
- 新增 `providers/funasr_asr.py`，作为默认本地 ASR provider，用于获取真实中文时间戳。
- Aliyun ASR 保留为备用 provider，但默认 `asr.allow_fallback=false`，避免 FunASR 失败时静默退回文本 ASR 并生成不可信的估算时间轴。

## P7 真实冒烟测试和参数调整（2026-05-06）

- 使用 `D:\video_test\130990752.mp4` 跑通完整 smoke test。
- 确认 FunASR 输出真实 provider 时间戳；例如 `欢迎 JUZ` 不再被估算到 9 秒，而是落在约 `3.940-4.745`。
- DashScope LLM 从 `qwen3.6-plus` 改为 `qwen-plus`。原因：
  - 当前 key 可访问 `qwen-plus`。
  - `qwen-plus-latest`、`qwen-turbo-latest`、`qwen-max-latest` 返回 `Model.AccessDenied`。
  - `qwen3.6-plus` 可访问，但实际效果不采用。
- DashScope LLM timeout 从 `60s` 提高到 `180s`，避免内容清理阶段偶发 read timeout。
- 暂停剪辑参数调整：
  - `pause_cut.target_pause_duration` 从 `0.10` 调到 `0.14`。
  - 开启 `pause_cut.use_word_gaps`。
  - 新增 `pause_cut.word_gap_threshold=0.80`，只切明显段内空白，不切普通短犹豫。
- 最终测试样例生成 8 个 pause 压缩，能切掉段内约 5 秒死空白，同时避免 0.4 秒左右的普通口播停顿被过度压缩。

## P8 Windows 依赖锁定（2026-05-06）

- 定位 `.venv` 卡在 `FunASR importing runtime` 的原因：不是下载模型，而是导入 PyTorch 时失败。
- `torch 2.11.0+cpu` 在当前 `.venv` 中触发：

```text
WinError 1114 ... c10.dll
```

- 降级并验证可用版本：

```text
numpy 1.26.4
torch 2.2.2+cpu
torchaudio 2.2.2+cpu
funasr import ok
```

- 更新 `requirements.txt`：
  - 锁定 `torch==2.2.2+cpu`
  - 锁定 `torchaudio==2.2.2+cpu`
  - 限制 `numpy<2`
  - 增加 PyTorch CPU wheel index
- 使用 `.venv` 成功跑通：

```powershell
D:\project\.venv\Scripts\python.exe -m scripts.dev_smoke_test "D:\video_test\130990752.mp4"
```

- 更新 README 为中文，明确安装、验证、启动、常见问题和模型权限说明。

## P9 局部语义重复删除（2026-05-06）

- 增加两级语义去重机制：粗语义段先判断重复，过长候选再按原始 transcript segment 和 provider word 边界做局部 refine。
- 新增 `prompts/local_semantic_dedup.md`，要求 LLM 只输出短局部 `delete_ranges`，不允许整段大删。
- 新增配置：
  - `dedup.enable_local_refine=true`
  - `dedup.local_refine_max_delete_duration=3.0`
  - `dedup.local_refine_min_confidence=0.90`
  - `dedup.local_refine_boundary_guard=0.08`
  - `dedup.local_refine_max_total_delete_duration_per_semantic_segment=5.0`
- 安全策略：
  - 只自动执行 provider word 边界上的局部删除。
  - 单个候选过长、低置信、边界不可信或累计删除超限时进入 `review_needed`。
  - `content_cleanup.auto_delete_enabled` 继续保持 `false`。
- 增加局部 refine 单元测试，覆盖成功删除、过长拒绝、低置信拒绝、累计上限和缺失 provider timestamp。

## P10 实战样例对齐调参（2026-05-06）

- 使用 `D:\video_test\video__03 .mp4` 作为真实样例，使用 `D:\video_test\video__03_label.mp4` 作为人工剪辑模板对照。
- 初始输出约 `115.03s`，模板约 `92.74s`，主要问题是没有片头空白删除、语义删除为 0、气口保留偏宽。
- 扩展语义去重：当 LLM 只返回 `review_needed` 语义段时，也对这些语义段执行局部 refine；仍只允许 provider word 边界、高置信、短范围删除。
- 实战样例中局部语义删除生效，生成 4 个 `semantic_dedup delete`，包括 ASR 幻听、重复改口和重复提醒。
- 增加 `pause_cut.trim_edge_silence=true`，对第一句前和最后一句后的长空白执行压缩。
- 将 standard 口播气口调到更接近模板：
  - `pause_cut.target_pause_duration=0.04`
  - `pause_cut.word_padding=0.01`
- 调整后样例输出约 `98.34s`，相比模板还差约 `5.60s`；剩余主要来自语义删除后新暴露的 gap，后续可增加 post-delete pause pass。

## P11 后置气口、字幕纠错和高质量渲染（2026-05-06）

- 增加后置气口检测：在 `resolve_edit_boundaries` 之后，根据已经确定的语义删除和气口压缩重新映射时间轴，检测语义删除后新暴露的长空白，并追加 `pause_detector compress_pause`。
- 调整 `plan_edits` 合并规则：pause 与 delete 重叠时不再整条丢弃 pause，而是从 pause 中扣除 delete 区间，保留仍然有效的空白压缩范围。
- 新增 `prompts/subtitle_correction.md` 和 `scripts/correct_subtitles.py`：LLM 只纠正明显 ASR 错字、同音误识别、断词和标点问题，不允许修改时间戳、segment_id 或词级边界。
- 新增 `subtitle_correction` 配置，默认开启，并通过 `max_length_ratio` 防止字幕被扩写、总结或改写原意。
- 字幕纠错改为分块调用，并增加 `min_similarity` 相似度校验；如果 LLM 把后文错填到当前 segment，候选会被拒绝并保留原字幕。
- 增加数字短语保护，避免字幕纠错把金额、日期、数量级等数字表达重排或改写。
- 字幕纠错结果写回 `remapped_transcript.json`，后续 `transcript_after_edit.md` 和 `subtitles.ass` 都使用纠错后的文本。
- 渲染质量参数从 `crf=23/preset=medium/profile=main` 调整为最终输出 `crf=16/preset=slow/profile=high`，并新增中间文件 `intermediate_crf=12`，降低切片、合并、烧字幕多次重编码的代际损失。由于当前流程需要剪辑并烧录 ASS 字幕，视频流必须重编码，不能做到真正无损直拷。
- 增加字幕纠错单元测试和后置气口单元测试；全量单测通过 `61 passed`。

## P12 编号语义单元删除主链路（2026-05-06）

- 将语义删除主链路从“LLM 输出局部 start/end”改为“编号语义单元 -> LLM 返回 unit_id -> 连贯性复核 -> 整 unit 删除”。
- 新增 `utterance_units.json`，每个 unit 使用 provider word 边界，包含原文和仅供语义判断使用的 `analysis_text`。
- 新增分析文本纠错 prompt，用于帮助 LLM 正确理解 ASR 错字，但不改变剪辑时间戳。
- 新增删除后连贯性复核，只有删除后前后文本自然、完整、可朗读时才生成 `semantic_dedup delete`。
- 气口检测顺序调整为语义删除之后执行；post-delete pause 只压缩删除造成的新 gap，不再处理普通 word gap。
- 移除面向单个样例的领域词硬规则，不再按“出口/出海/迎”等固定词判断是否 review。
- 实战样例 `D:\video_test\video__03 .mp4` 跑通：生成 50 个 utterance units、30 条最终 edits、2 条 unit 级语义删除；36s 左右不再残留“其/次”，第二段后不再跳到授权金额。
- 全量单测通过 `72 passed`。

## P13 视频包装、边界与字幕纠错增强（2026-05-08）

- 新增封面图与视频内固定叠字：右上角标题、底部人物介绍、三行风险提示，输出 `cover.png`、`cover.ass`、`visual_overlay.ass`。
- 固定叠字支持自动测量、缩放、换行和最终截断保护；样式与位置集中在 `visual_overlay.layout`。
- 渲染改为优先使用 `filter_complex` 一次完成剪切、拼接和烧字幕，减少多段临时文件带来的慢速问题。
- 语义删除增加边界 padding 与极短保留碎片合并，减少剪辑后残留尾音、爆破音。
- 字幕纠错增加前后上下文和 `analysis_text` 参考候选，但不强制采纳，仍保留长度/相似度/数字短语安全校验。
- `config.default.yaml` 增加中文注释，说明主要参数用途和调大/调小影响。

## P14 字级局部口误修剪（2026-05-08）

- 新增 `local_false_start_refine`：当完整 unit 删除失败但 review 显示明显口误、改口、残句或重述时，进入 provider 字级修剪。
- 新增 `prompts/local_false_start_refine.md`，要求 LLM 只能返回连续 `word_id` 范围，不能直接返回任意时间戳。
- 字级修剪会校验 provider 时间戳、置信度、删除时长、剩余文本长度，并再次做连贯性复核。
- 通过复核后生成 `local_false_start_refine` 删除决策，并继续走现有边界 padding 与碎片合并，避免残留人声。
- 增加单元测试覆盖成功修剪和连贯性失败保留 review；全量测试通过 `85 passed`。
