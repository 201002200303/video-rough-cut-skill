# dev_log

## P1 基础骨架与协议 (04-28)
- 建立 FastAPI + SQLite + 单 Worker 架构；实现 jobs 创建/查询/输出接口与失败隔离 worker。
- 完成核心 schemas：Transcript/Word/SemanticSegment/EditDecision/SkillInput/SkillOutput/JobStatus/JobRecord，时间统一为秒级 float。
- core 完成 config/env、paths、logging、exceptions；支持 `VIDEO_SKILL_CONFIG` 与 `VIDEO_SKILL_DB_PATH`。

## P2 FFmpeg与完整流水线 (04-28)
- 实现 `extract_audio`、视频探测、FFmpeg 可用性检查；命令失败统一抛 `ExternalCommandError`。
- 实现 `detect_pauses`、`build_semantic_segments`、`detect_repetition`、`plan_edits`、`remap_timeline`、`generate_subtitles`、`render_video`、`generate_report`。
- `run_pipeline` 串联 extract/transcribe/detect/remap/subtitle/render/report 并落盘中间产物。

## P3 DashScope真实链路 (04-28)
- LLM 接入 DashScope compatible API，默认 `qwen-plus-latest`，支持 `DASHSCOPE_LLM_MODEL` 与 `DASHSCOPE_API_BASE_URL`。
- ASR 接入 Qwen-ASR `qwen3-asr-flash` compatible/chat 与 DashScope 同步调用；纯文本结果会生成 `estimated` word timestamp。
- 修复 Windows ASS filter 路径转义，实机视频可生成最终字幕视频与中间产物。

## P4 参数集中化与剪辑尾帧修复 (04-29)
- `config.default.yaml` 集中 pause_cut、dedup、content_cleanup、vad、boundary_resolver、subtitle、render、aliyun、modes 参数。
- `remap_timeline` 对部分重叠删除改为 clamp 截断，避免正常片段末尾被整段丢弃。
- 字幕样式从 config 读取，解决字幕越界相关参数散落问题。
- `run.py` 接入模式覆盖：`conservative` / `standard` / `aggressive`。

## P5 内容清理与误删保护 (04-29)
- 新增 `detect_content_cleanup`，用于识别语气词、尾部废话、ASR 幻听等低价值内容。
- `dedup` / `content_cleanup` 增加 `max_auto_delete_duration`，长删段转人工 review。
- `content_cleanup.auto_delete_enabled` 默认关闭；在 ASR 时间戳不可靠时只输出候选，避免自动剪坏句头/尾音。
- `remap_timeline` 部分删除后重建 segment text，保证字幕与保留 words 一致。

## P6 VAD与边界护栏 (04-29)
- 新增 `detect_vad` 生成 `vad_segments.json`，提供静音/非静音边界参考。
- `TranscriptWord` 增加 `timestamp_source: provider|estimated`。
- 新增 `resolve_edit_boundaries`：LLM 删除若依赖 `estimated` word timestamp，默认转入 `review_needed`；provider 时间戳可按 VAD 静音边界吸附。

## P7 剪辑调试产物 (04-29)
- 新增 `transcript_before_edit.md` / `transcript_after_edit.md`，逐句列出 start/end/duration/text 与 word 边界。
- 有实际 edits 时追加剪辑策略、影响文本、原因、置信度和判断标准，便于复盘误剪。

## P8 Qwen-ASR FileTrans真实时间戳 (04-29)
- `aliyun_asr.py` 接入 Qwen-ASR FileTrans：`qwen3-asr-flash-filetrans` + `enable_words=true`。
- 解析 `transcripts[].sentences[].words[].begin_time/end_time/text/punctuation`，写入 `timestamp_source=provider`；英文按 provider words 保留边界。
- 支持本地 `audio.wav` 临时上传为 DashScope OSS 地址；配置项写入 README/.env.example/config。
- 实测当前 Key：北京 FileTrans 提交返回 `Model.AccessDenied`，国际站返回 `InvalidApiKey`；代码路径与解析逻辑已完成，需开通/更换北京地域 FileTrans Key。
- 回归：`pytest` 86/86 passed。

## P9 输出视频兼容性加固 (04-29)
- render 增加 `video_profile/video_level/movflags` 可配置，默认 `main + 4.0 + +faststart`。
- 目标是降低“PC 播放器提示文件无效、手机可播”的容器/索引兼容性问题。

## P10 口播剪辑参数收紧 (04-29)
- `pause_cut`：默认略收紧；新增 `sentence_boundary_pause_bonus` 可配置句尾气口保护强度。
- `dedup.similarity_threshold` 0.82；`content_cleanup.auto_delete_enabled` 与「仅 review」策略对齐为 false。
- `modes`：conservative / aggressive 与默认拉开，便于留气口或扫死气。
