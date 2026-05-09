# Video Rough Cut Skill

中文口播视频粗剪 Skill，用于把本地中文单人口播、财经复盘、课程讲解等视频处理成带字幕、封面图、固定叠字和风险提示的粗剪成片。

这个项目的定位不是 Web 服务，也不是通用剪辑软件，而是给 Codex 或本地命令行调用的一条确定性视频处理流水线：FunASR 负责本地转写和时间戳，Qwen LLM 负责语义删除候选、连贯性复核和字幕纠错，FFmpeg 负责音频提取、剪切拼接、字幕烧录、封面生成。

## 适用场景

- 中文口播视频自动粗剪。
- 压缩停顿、清理重复表达、处理明显改口或 false start。
- 生成 ASS 字幕并烧录到视频。
- 生成封面图、右上角标签、底部人物介绍和固定提示语。
- 输出可复查的转写、剪辑决策和报告文件。

不适合的场景：

- 多机位精剪、复杂 B-roll 编排、音乐卡点剪辑。
- 多人说话的精确说话人分离。
- 需要人工审美判断的大幅内容重组。
- 长期运行的 HTTP 服务或队列系统。

## 环境要求

- Python 3.10 到 3.12。当前依赖锁定了 `torch==2.2.2+cpu`，不建议使用 Python 3.13。
- FFmpeg 和 FFprobe，并且需要能在命令行中直接运行 `ffmpeg`、`ffprobe`。
- DashScope API Key，用于 Qwen LLM 调用。默认本地 ASR 使用 FunASR，但语义删除、连贯性复核、字幕纠错需要 `DASHSCOPE_API_KEY`。
- 建议准备一段竖屏中文口播视频，例如 `mp4` 文件。

## Windows 启动

以下命令默认在 PowerShell 中执行。

1. 进入项目目录：

```powershell
cd D:\project_main\video_rough_cut_skill
```

2. 一键准备运行环境：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```

这个脚本会：

- 自动创建 `.venv` 虚拟环境。
- 检查并安装 Python 依赖。
- 检查 `ffmpeg` / `ffprobe`。
- Windows 下通过 `winget install Gyan.FFmpeg` 安装 FFmpeg。
- 自动查找 winget 安装出的 `ffmpeg.exe`，并把它所在的 `bin` 目录加入当前用户 `PATH`。
- 如果 `.env` 不存在，自动从 `.env.example` 创建。

如果只想修复 FFmpeg/PATH，不安装 Python 依赖，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -SkipPythonDeps
```

如果脚本更新了 `PATH`，请关闭并重新打开 PowerShell、CMD 或 Codex 终端，然后验证：

```powershell
ffmpeg -version
ffprobe -version
```

3. 配置环境变量。

脚本通常已经创建 `.env`。打开它并填入自己的 DashScope Key：

```powershell
notepad .env
```

至少需要设置：

```dotenv
DASHSCOPE_API_KEY=你的_dashscope_api_key
DASHSCOPE_LLM_MODEL=qwen-plus
FUNASR_DEVICE=cpu
```

4. 激活虚拟环境并运行粗剪流水线：

```powershell
.\.venv\Scripts\Activate.ps1
python -m scripts.run --video "D:\data\input.mp4" --output-dir "D:\data\rough_cut_out" --mode standard
```

带封面和叠字参数的示例：

```powershell
python -m scripts.run `
  --video "D:\data\input.mp4" `
  --output-dir "D:\data\rough_cut_out" `
  --mode standard `
  --cover-title "今日看盘\n重点提醒" `
  --date-label "2026.05.09" `
  --cover-subtitle "看盘笔记" `
  --top-right-label "0509 收评" `
  --insert-cover-seconds 0
```

## Linux 启动

以下命令以 Ubuntu/Debian 系为例。

1. 进入项目目录：

```bash
cd /path/to/video_rough_cut_skill
```

2. 一键准备运行环境：

```bash
bash scripts/setup_linux.sh
```

这个脚本会自动创建 `.venv`、安装 Python 依赖、创建 `.env`，并优先检测 `ffmpeg` / `ffprobe`；如果缺失，会在常见 Linux 发行版上尝试使用 `apt`、`dnf`、`yum` 或 `pacman` 安装 `ffmpeg`。安装后验证：

```bash
ffmpeg -version
ffprobe -version
```

如果只想修复 FFmpeg，不安装 Python 依赖，可以运行：

```bash
bash scripts/setup_linux.sh --skip-python-deps
```

3. 配置环境变量：

脚本通常已经创建 `.env`。打开它并填入自己的 DashScope Key：

```bash
nano .env
```

至少需要设置：

```dotenv
DASHSCOPE_API_KEY=你的_dashscope_api_key
DASHSCOPE_LLM_MODEL=qwen-plus
FUNASR_DEVICE=cpu
```

也可以只在当前终端临时设置：

```bash
export DASHSCOPE_API_KEY="你的_dashscope_api_key"
export DASHSCOPE_LLM_MODEL="qwen-plus"
export FUNASR_DEVICE="cpu"
```

4. 激活虚拟环境并运行粗剪流水线：

```bash
source .venv/bin/activate
python -m scripts.run --video "/data/input.mp4" --output-dir "/data/rough_cut_out" --mode standard
```

带封面和叠字参数的示例：

```bash
python -m scripts.run \
  --video "/data/input.mp4" \
  --output-dir "/data/rough_cut_out" \
  --mode standard \
  --cover-title $'今日看盘\n重点提醒' \
  --date-label "2026.05.09" \
  --cover-subtitle "看盘笔记" \
  --top-right-label "0509 收评" \
  --insert-cover-seconds 0
```

## 运行模式

通过 `--mode` 选择剪辑激进程度：

- `standard`：默认模式，平衡节奏和安全性。
- `conservative`：更保守，少剪停顿，语义删除更谨慎。
- `aggressive`：更激进，停顿压缩更明显，重复判断更宽松。

示例：

```bash
python -m scripts.run --video "/data/input.mp4" --output-dir "/data/out" --mode conservative
```

## 常用参数

- `--video`：输入视频路径，必填。
- `--output-dir`：输出目录，必填。
- `--mode`：运行模式，默认 `standard`。
- `--visual-metadata`：可选 JSON 文件，用于一次性传入视觉包装信息。
- `--cover-title`：封面大标题，支持 `\n` 换行。
- `--date-label`：封面日期，例如 `2026.05.09`。
- `--cover-subtitle`：封面左下角小标题。
- `--top-right-label`：视频内右上角标签。
- `--person-intro`：底部人物介绍。
- `--insert-cover-seconds`：是否把封面作为片头插入；`0` 表示只生成封面图，不插入视频。

视觉参数也可以写成 JSON：

```json
{
  "cover_title": "今日看盘\n重点提醒",
  "date_label": "2026.05.09",
  "cover_subtitle": "看盘笔记",
  "top_right_label": "0509 收评",
  "person_intro": "某某投顾 登记编号：A00000000000000",
  "insert_cover_seconds": 0
}
```

然后运行：

```bash
python -m scripts.run --video "/data/input.mp4" --output-dir "/data/out" --visual-metadata "/data/visual.json"
```

## 输出文件

运行完成后，输出目录中通常会包含：

- `edited_video_with_yellow_subtitles.mp4`：最终成片。
- `cover.png`：封面图。
- `audio.wav`：从输入视频提取的音频。
- `transcript.json`：原始转写结果。
- `semantic_segments.json`：语义段落。
- `utterance_units.json`：编号口播单元。
- `edit_decisions.json`：剪辑决策，包括删除和停顿压缩。
- `remapped_transcript.json`：剪辑后的时间线转写。
- `subtitles.ass`：主字幕文件。
- `visual_overlay.ass`：带固定叠字的字幕文件。
- `cover.ass`：封面叠字文件。
- `transcript_before_edit.md`：剪辑前文本调试文件。
- `transcript_after_edit.md`：剪辑后文本调试文件。
- `edit_report.md`：剪辑报告。

## 配置

默认配置在 `config.default.yaml`。常见可调区域：

- `pause_cut`：停顿压缩阈值和保留时长。
- `dedup`：语义删除、重复表达检测、连贯性复核。
- `content_cleanup`：额外内容清理，默认关闭。
- `subtitle`：主字幕字体、字号、颜色、位置。
- `visual_overlay`：封面、右上角标签、底部介绍和固定提示语。
- `render`：FFmpeg 编码参数和渲染策略。
- `aliyun.llm`：Qwen LLM 模型、温度、超时。
- `funasr`：本地 ASR 模型、设备和句级时间戳。

如果不想直接修改默认配置，可以新建一个覆盖配置文件，并通过环境变量指定：

Windows PowerShell：

```powershell
$env:VIDEO_SKILL_CONFIG="D:\data\my.video-skill.yaml"
python -m scripts.run --video "D:\data\input.mp4" --output-dir "D:\data\out"
```

Linux：

```bash
export VIDEO_SKILL_CONFIG="/data/my.video-skill.yaml"
python -m scripts.run --video "/data/input.mp4" --output-dir "/data/out"
```

## 作为 Codex Skill 使用

当 Codex 使用这个 Skill 时，推荐流程是：

1. 先确认输入视频路径和输出目录。
2. 询问封面标题、日期、右上角标签、人物介绍、是否插入封面片头。
3. 如果用户不提供视觉文案，就使用配置默认值和转写内容生成视觉元数据。
4. 优先使用 `standard` 模式；用户强调“少剪”时用 `conservative`，强调“节奏更紧”时用 `aggressive`。
5. 运行 `python -m scripts.run`，不要让 LLM 直接拼接 FFmpeg 命令做剪辑决策。
6. 完成后把最终视频、封面、报告和关键 JSON 路径反馈给用户。

这个 Skill 的核心原则是：LLM 只提出语义候选和文本修正，真实剪切边界必须经过脚本校验，并尽量依赖 provider 级时间戳。

## 测试

安装依赖后可以运行：

```bash
pytest
```

Windows PowerShell 同样可以执行：

```powershell
pytest
```

测试会覆盖字幕、时间线重映射、剪辑决策、VAD 边界、视觉叠字等核心逻辑。

## 常见问题

### `ffmpeg` 或 `ffprobe` 找不到

说明 FFmpeg 没有安装，或没有加入 `PATH`。安装后重新打开终端，再运行：

```bash
ffmpeg -version
ffprobe -version
```

### 安装 `torch==2.2.2+cpu` 失败

确认 Python 版本是 3.10 到 3.12，并且 `requirements.txt` 中的 PyTorch CPU wheel 源没有被删除。

### LLM 调用失败

检查 `.env` 中的 `DASHSCOPE_API_KEY` 是否正确，模型是否有权限。默认建议使用：

```dotenv
DASHSCOPE_LLM_MODEL=qwen-plus
```

### 首次运行很慢

FunASR 和 PyTorch 相关依赖较大，首次安装和模型初始化会比较慢。长视频还会增加 ASR、LLM 和 FFmpeg 渲染时间。

### 输出字幕字体不对

确认机器上安装了 `config.default.yaml` 里 `subtitle.font_name` 指定的字体。没有对应字体时，FFmpeg/libass 会回退到其他字体。
