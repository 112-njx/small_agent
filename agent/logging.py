"""统一日志：控制台 + 文件双输出，为工具 trace 预留独立 logger。

设计：
- 根命名空间 `agent`：所有业务模块用 `logging.getLogger("agent.xxx")` 记录，
  `setup_logging()` 一次性为其挂上控制台与滚动文件 handler。
- 预留 `agent.tools` 独立 logger：工具系统（Step 3）与主循环（Step 4）
  将用它记录每次工具调用的参数 / 结果摘要 / 耗时，方便单独过滤 trace。
- 幂等：重复调用 `setup_logging()` 不会叠加 handler。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Union

from agent.config import VALID_LOG_LEVELS, Settings
from agent.errors import ConfigError

ROOT_LOGGER_NAME = "agent"
TOOL_TRACE_LOGGER_NAME = "agent.tools"  # 工具 trace 预留 logger
SESSION_LOGGER_NAME = "agent.session"  # 会话管理预留 logger

DEFAULT_LOG_FILE = "agent.log"
DEFAULT_MAX_BYTES = 1_000_000  # 单文件 1MB
DEFAULT_BACKUP_COUNT = 3

_configured = False


def _normalize_level(level: Union[str, int]) -> int:
    """把字符串 / int 日志级别归一化为 int，非法值抛 ConfigError。"""
    if isinstance(level, int):
        return level
    name = str(level).strip().upper()
    if name not in VALID_LOG_LEVELS:
        raise ConfigError(
            f"日志级别非法：{level!r}。可选值：{', '.join(sorted(VALID_LOG_LEVELS))}。"
        )
    return logging.getLevelName(name)


def setup_logging(
    level: Union[str, int] = "INFO",
    log_dir: str | Path = "logs",
    log_file: str = DEFAULT_LOG_FILE,
    *,
    console: bool = True,
) -> logging.Logger:
    """配置 `agent` 命名空间日志：控制台 + 滚动文件。

    Args:
        level: 日志级别（字符串或 logging 级别 int）。
        log_dir: 日志目录，不存在则自动创建。
        log_file: 日志文件名。
        console: 是否挂控制台 handler。

    Returns:
        根 logger（`agent`），业务模块通过 `logging.getLogger("agent.xxx")` 使用。
    """
    global _configured

    log_level = _normalize_level(level)

    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger(ROOT_LOGGER_NAME)
    root_logger.setLevel(log_level)
    root_logger.propagate = False  # 避免与第三方库的根 logger 配置互相污染

    if _configured:
        return root_logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_dir_path / log_file,
        maxBytes=DEFAULT_MAX_BYTES,
        backupCount=DEFAULT_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # 子 logger 默认继承根 handler；显式设置 level=NOTSET 表示跟随父级
    logging.getLogger(TOOL_TRACE_LOGGER_NAME).setLevel(logging.NOTSET)
    logging.getLogger(SESSION_LOGGER_NAME).setLevel(logging.NOTSET)

    _configured = True
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """获取 `agent.` 命名空间下的业务 logger。"""
    if not name.startswith(ROOT_LOGGER_NAME + "."):
        name = f"{ROOT_LOGGER_NAME}.{name}"
    return logging.getLogger(name)


def get_tool_trace_logger() -> logging.Logger:
    """工具 trace 专用 logger（参数 / 结果摘要 / 耗时）。"""
    return logging.getLogger(TOOL_TRACE_LOGGER_NAME)


def configure_from_settings(settings: Settings) -> logging.Logger:
    """按已加载的 Settings 配置日志（供 `python -m agent` 等入口复用）。"""
    return setup_logging(level=settings.log_level, log_dir=settings.log_dir)


__all__ = [
    "ROOT_LOGGER_NAME",
    "TOOL_TRACE_LOGGER_NAME",
    "SESSION_LOGGER_NAME",
    "setup_logging",
    "get_logger",
    "get_tool_trace_logger",
    "configure_from_settings",
]
