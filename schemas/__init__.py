"""数据协议模块 — 视频粗剪技能的数据模型。"""

from schemas.transcript import TranscriptWord, TranscriptSegment, Transcript
from schemas.segment import SemanticSegment
from schemas.edit_decision import EditDecision, EditDecisionFile
from schemas.skill_input import SkillInput
from schemas.skill_output import SkillOutput
from schemas.subtitle import SubtitleEvent, SubtitleData
from schemas.job import (
    JobStatus,
    JobRecord,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
)

__all__ = [
    "TranscriptWord",
    "TranscriptSegment",
    "Transcript",
    "SemanticSegment",
    "EditDecision",
    "EditDecisionFile",
    "SkillInput",
    "SkillOutput",
    "SubtitleEvent",
    "SubtitleData",
    "JobStatus",
    "JobRecord",
    "JOB_STATUS_PENDING",
    "JOB_STATUS_RUNNING",
    "JOB_STATUS_COMPLETED",
    "JOB_STATUS_FAILED",
]