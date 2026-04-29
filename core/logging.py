"""技能日志配置。"""

import logging
import sys


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """创建并配置结构化日志器。

    格式：timestamp [LEVEL] module: message

    参数:
        name: 日志器名称（通常为模块 __name__）。
        level: 日志级别字符串。

    返回:
        已配置的 Logger 实例。
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    return logger