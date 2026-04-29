"""视频粗剪技能自定义异常。"""


class SkillError(Exception):
    """所有技能异常的基类。"""


class ExternalCommandError(SkillError):
    """外部命令（如 FFmpeg）失败时抛出。"""


class ProviderError(SkillError):
    """外部提供者（ASR/LLM）调用失败时抛出。"""


class ValidationError(SkillError):
    """数据校验失败时抛出。"""


class ConfigError(SkillError):
    """配置无效或缺失时抛出。"""