# Video Rough Cut Skill

中文口述视频自动粗剪 MVP（FastAPI + SQLite + 单 Worker），当前面向真实 DashScope/FFmpeg 链路运行。

## 项目介绍

输入 mp4/mov 口述视频，自动生成：
- `audio.wav`
- `vad_segments.json`
- `transcript.json`
- `transcript_before_edit.md`
- `transcript_after_edit.md`
- `edit_decisions.json`
- `remapped_transcript.json`
- `subtitles.ass`
- `edit_report.md`
- `edited_video_with_yellow_subtitles.mp4`

## 安装依赖

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## FFmpeg 要求

- 需要 `ffmpeg` 与 `ffprobe` 在 PATH 中可用。
- 可通过 `python -m scripts.dev_smoke_test /path/to/test.mp4` 自动检查。

## 环境变量

- `VIDEO_SKILL_DB_PATH`（可选，默认 `./video_skill.db`）
- `VIDEO_SKILL_CONFIG`（可选，自定义 YAML 配置路径，会覆盖 `config.default.yaml`）
- `DASHSCOPE_API_KEY`（必需，用于 ASR 与 LLM）
- `DASHSCOPE_API_BASE_URL`（默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`）
- `DASHSCOPE_LLM_MODEL`（默认 `qwen-plus-latest`）
- `DASHSCOPE_ASR_MODEL`（默认 `qwen3-asr-flash`）
- `DASHSCOPE_ASR_ENABLE_WORD_TIMESTAMPS`（默认 `true`，启用 Qwen-ASR FileTrans `enable_words`）
- `DASHSCOPE_ASR_FILETRANS_MODEL`（默认 `qwen3-asr-flash-filetrans`）
- `DASHSCOPE_ASR_FILETRANS_FILE_URL`（可选，公网 HTTP/HTTPS/oss:// 音频 URL）
- `DASHSCOPE_ASR_FILETRANS_AUTO_UPLOAD`（默认 `true`，无 URL 时用 DashScope 临时 OSS 上传本地音频）

> 当前不再提供 mock 自动兜底。未配置 `DASHSCOPE_API_KEY` 时，ASR/LLM 步骤会失败。

## 调参入口

主要剪辑与渲染参数集中在 `config.default.yaml`，也可通过 `VIDEO_SKILL_CONFIG` 指向自定义 YAML 覆盖：

- `pause_cut`：停顿压缩阈值、压缩后保留时长、`sentence_boundary_pause_bonus`（句尾标点处更保守）、word gap 检测。
- `dedup`：语义去重窗口、相似度阈值、低置信度处理。
- `vad`：静音/非静音边界检测参数。
- `boundary_resolver`：LLM 删除候选进入实际剪辑前的边界安全护栏。
- `semantic_segment`：语义段合并长度。
- `modes`：`conservative` / `standard` / `aggressive` 的阈值覆盖。
- `subtitle`：字体、字号、行宽、分辨率基准、边距。
- `render`：视频编码器、CRF、preset、像素格式。
- `aliyun`：ASR/LLM 模型、base URL、采样率、超时等。

## 启动 API

```bash
uvicorn api.app:app --host 0.0.0.0 --port 8000
```

## 启动 Worker

```bash
python -m api.worker
```

## 创建任务（curl）

```bash
curl -X POST "http://127.0.0.1:8000/jobs" \
  -H "Content-Type: application/json" \
  -d "{\"input_video_path\":\"D:/data/test.mp4\",\"output_dir\":\"D:/data/out\",\"mode\":\"standard\"}"
```

## 查询任务（curl）

```bash
curl "http://127.0.0.1:8000/jobs/<job_id>"
curl "http://127.0.0.1:8000/jobs/<job_id>/outputs"
```

## 真实链路说明

- ASR：`providers/aliyun_asr.py` 默认调用 Qwen-ASR FileTrans，并开启 `enable_words` 解析真实词/字级时间戳；关闭 `enable_word_timestamps` 后才回退到纯文本 Qwen-ASR。
- LLM：`providers/aliyun_qwen.py` 通过 DashScope 兼容接口执行近邻语义去重。
- VAD：`scripts/detect_vad.py` 用 FFmpeg `silencedetect` 生成 `vad_segments.json`，提供静音/非静音边界参考。
- 边界解析：`scripts/resolve_edit_boundaries.py` 会阻止基于 `estimated` word timestamp 的 LLM 删除自动执行。
- FFmpeg：负责音频提取、确定性切片/拼接和 ASS 字幕烧录。

## 时间戳与剪辑安全

`transcript.json` 中每个 word 带有 `timestamp_source`：

- `provider`：ASR 服务真实返回的 word timestamp，可作为自动剪辑边界候选。
- `estimated`：项目按文本长度估算的时间戳，只能用于字幕和粗参考，不能直接自动剪。

默认 Qwen-ASR FileTrans 会请求 `enable_words=true`。结果文件中的 `transcripts[].sentences[].words[].begin_time/end_time/text/punctuation` 会写入 `transcript.json`，并标记为 `provider`。中文会偏字级，英文会按英文词返回，便于核对英文词边界。

如果 FileTrans 未开通或手动关闭 `enable_word_timestamps`，纯文本 Qwen-ASR 路径会将 word timestamp 标记为 `estimated`。这类时间戳只能用于字幕和粗参考，LLM 删除会被边界护栏转入 `review_needed`。

## 阿里云接入点

- ASR Provider：`providers/aliyun_asr.py`
- LLM Provider：`providers/aliyun_qwen.py`
- LLM 默认走 DashScope Compatible Chat Completions，模型建议 `qwen-plus-latest`

## 开发自检

```bash
pytest
python -m scripts.dev_smoke_test /path/to/test.mp4
```

## 实际操作流程（Windows）

1. 进入项目并激活虚拟环境：

```powershell
cd d:\project\new_project\video_rough_cut_skill
.\.venv\Scripts\Activate.ps1
```

2. 准备环境变量（推荐放在项目根目录 `.env`）：

```env
DASHSCOPE_API_KEY=你的key
DASHSCOPE_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_LLM_MODEL=qwen-plus-latest
DASHSCOPE_ASR_MODEL=qwen3-asr-flash
DASHSCOPE_ASR_ENABLE_WORD_TIMESTAMPS=true
DASHSCOPE_ASR_FILETRANS_MODEL=qwen3-asr-flash-filetrans
DASHSCOPE_ASR_FILETRANS_AUTO_UPLOAD=true
```

3. 单条命令直接跑完整 pipeline（不依赖 API/Worker）：

```powershell
python -m scripts.run --video "E:\迅雷下载\test_0.mp4" --output-dir "E:\迅雷下载\video_skill_runs\test_0" --mode standard
```

4. 四个测试视频批量执行：

```powershell
$videos = @("test_0.mp4","test_1.mp4","test_2.mp4","test_3.mp4")
foreach ($v in $videos) {
  $name = [System.IO.Path]::GetFileNameWithoutExtension($v)
  python -m scripts.run --video ("E:\迅雷下载\" + $v) --output-dir ("E:\迅雷下载\video_skill_runs\" + $name) --mode standard
}
```

5. 每个视频输出目录包含以下文件：
- `audio.wav`
- `vad_segments.json`
- `edited_video_with_yellow_subtitles.mp4`
- `transcript.json`
- `transcript_before_edit.md`
- `transcript_after_edit.md`
- `edit_decisions.json`
- `remapped_transcript.json`
- `subtitles.ass`
- `edit_report.md`

## 四视频实测记录（2026-04-29）

- 输入目录：`E:\迅雷下载`
- 测试文件：`test_0.mp4`、`test_1.mp4`、`test_2.mp4`、`test_3.mp4`
- 输出目录：`E:\迅雷下载\video_skill_runs\test_0..test_3`
- 结果：4/4 全部成功跑通（extract/transcribe/detect/repeat/remap/subtitle/render/report）

## 剪辑调试文件

每次运行会额外生成两份便于人工审查的 Markdown：

- `transcript_before_edit.md`：剪辑前逐句时间轴，包含每个连续语句的 `start/end/duration/text`，并列出 word/短语级边界与 `timestamp_source`。
- `transcript_after_edit.md`：剪辑后对应逐句时间轴，用来检查剪辑后叙述是否连续。

如果本次有实际执行的剪辑，两个文件文末都会追加“实际剪辑策略”，包含：

- 操作类型：`delete` / `compress_pause`
- 操作时间段
- 影响文本
- 操作来源
- 原因
- 置信度
- 判断标准

如果没有实际修改，则不会追加策略说明。LLM 识别到但未执行的候选仍保存在 `edit_decisions.json` 的 `review_needed` 中。