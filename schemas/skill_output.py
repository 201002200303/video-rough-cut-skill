"""技能输出 Pydantic 模型。"""

from pydantic import BaseModel, Field


class SkillOutput(BaseModel):
    """视频粗剪技能输出模型。"""

    edited_video_path: str = Field(..., description="Path to the edited video with yellow subtitles")
    transcript_path: str = Field(..., description="Path to the transcript JSON file")
    edit_decisions_path: str = Field(..., description="Path to the edit decisions JSON file")
    subtitles_path: str = Field(..., description="Path to the ASS subtitles file")
    report_path: str = Field(..., description="Path to the edit report Markdown file")