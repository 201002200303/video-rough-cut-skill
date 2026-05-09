"""开发冒烟测试：端到端流水线验证。"""

import sys
from pathlib import Path

from core.utils import setup_logger
from scripts.extract_audio import check_ffmpeg_available
from scripts.run import run_pipeline

logger = setup_logger(__name__)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("用法: python -m scripts.dev_smoke_test /path/to/test.mp4")
    input_video = Path(sys.argv[1]).resolve()
    if not input_video.exists():
        raise SystemExit(f"输入视频未找到: {input_video}")
    output_dir = input_video.parent / f"{input_video.stem}_smoke_output"
    output = run_pipeline(input_video, output_dir, mode="standard")
    print("冒烟测试输出:")
    for k, v in output.model_dump().items():
        print(f"- {k}: {v}")
    must_exist = [
        Path(output.transcript_path),
        Path(output.edit_decisions_path),
        Path(output.subtitles_path),
        Path(output.report_path),
    ]
    for p in must_exist:
        if not p.exists():
            raise SystemExit(f"缺失预期输出: {p}")
    try:
        check_ffmpeg_available()
        if not Path(output.edited_video_path).exists():
            print("FFmpeg 可用但最终视频缺失。")
        else:
            print("最终视频已生成。")
    except Exception as exc:
        print(f"FFmpeg 不可用或渲染已跳过: {exc}")


if __name__ == "__main__":
    main()
