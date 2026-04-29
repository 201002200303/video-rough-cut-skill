# Skill: Video Rough Cut Skill

## 功能边界

- 做：中文口述视频粗剪（停顿压缩 + 近邻语义去重 + ASS 黄字 + FFmpeg 渲染）
- 不做：多人复杂对话、镜头级智能剪辑、特效包装、自动处理不确定语义

## 输入格式

```json
{
  "input_video_path": "D:/data/test.mp4",
  "output_dir": "D:/data/out",
  "mode": "standard"
}
```

## 输出格式

- `edited_video_with_yellow_subtitles.mp4`
- `transcript.json`
- `semantic_segments.json`
- `edit_decisions.json`
- `remapped_transcript.json`
- `subtitles.ass`
- `edit_report.md`

## Pipeline 步骤

1. `extract_audio`
2. `transcribe_audio`
3. `detect_pauses`
4. `build_semantic_segments`
5. `detect_repetition`
6. `plan_edits`
7. `remap_timeline`
8. `generate_subtitles`
9. `render_video`
10. `generate_report`

## 真实运行要求

- 必须安装并可执行 `ffmpeg` / `ffprobe`
- 必须提供 `DASHSCOPE_API_KEY`，用于真实 ASR 与 LLM 语义去重
- 主要参数集中在 `config.default.yaml`，可用 `VIDEO_SKILL_CONFIG` 指向覆盖配置
- `mode` 支持 `conservative` / `standard` / `aggressive`，会覆盖停顿与去重阈值

## 不做的事情

- LLM 不生成 FFmpeg 命令
- LLM 不直接控制完整剪辑流程
- ASR 不做删除判断
- FFmpeg 只做确定性切片/拼接/烧录

## 失败排查

1. 检查 `ffmpeg/ffprobe` 是否可执行
2. 检查 `output_dir` 是否有写权限
3. 检查 `edit_decisions.json` / `remapped_transcript.json` 是否存在
4. 检查 `DASHSCOPE_API_KEY`、模型名与 base URL 是否正确
5. 用 `python -m scripts.dev_smoke_test /path/to/test.mp4` 快速定位失败步骤