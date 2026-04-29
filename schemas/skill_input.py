"""技能输入 Pydantic 模型。"""

from pydantic import BaseModel, Field, field_validator


class SkillInput(BaseModel):
    """视频粗剪技能输入模型。"""

    input_video_path: str = Field(..., description="Path to the input video file (mp4/mov)")
    output_dir: str = Field(..., description="Directory for all output artifacts")
    mode: str = Field(default="standard", description="Processing mode: standard, conservative, aggressive")

    @field_validator("mode")
    @classmethod
    def valid_mode(cls, v: str) -> str:
        if v not in ("standard", "conservative", "aggressive"):
            raise ValueError("mode must be 'standard', 'conservative', or 'aggressive'")
        return v