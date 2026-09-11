"""配置加载：从 .env / 环境变量读取 LLM 与 Agent 运行配置。

加载顺序（后者覆盖前者）：
1. `.env` 文件（默认项目根目录，可用 `env_file` 参数覆盖）
2. 进程环境变量（`load_dotenv(override=False)` 保证真实环境变量优先级更高）

缺失必需项或取值非法时抛出 `ConfigError`，错误信息给出变量名与修复指引。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from dotenv import load_dotenv

from agent.errors import ConfigError

# ---- 环境变量名（与 .env.example 保持一致） ----
ENV_API_KEY = "LLM_API_KEY"
ENV_API_KEY_FALLBACK = "OPENAI_API_KEY"  # 兼容 openai SDK 原生读取的变量
ENV_BASE_URL = "LLM_BASE_URL"
ENV_MODEL = "LLM_MODEL"
ENV_MAX_ROUNDS = "AGENT_MAX_ROUNDS"
ENV_CONTEXT_THRESHOLD = "AGENT_CONTEXT_THRESHOLD"
ENV_LOG_LEVEL = "LOG_LEVEL"
ENV_LOG_DIR = "AGENT_LOG_DIR"

# ---- 默认值 ----
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_MAX_ROUNDS = 10
DEFAULT_CONTEXT_THRESHOLD = 8000  # 上下文阈值（估计 token 数），超过后触发基础压缩
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_DIR = "logs"

VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

PathLike = Union[str, os.PathLike]


@dataclass(frozen=True)
class Settings:
    """加载完成后的全部运行配置。"""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    max_rounds: int = DEFAULT_MAX_ROUNDS
    context_threshold: int = DEFAULT_CONTEXT_THRESHOLD
    log_level: str = DEFAULT_LOG_LEVEL
    log_dir: str = DEFAULT_LOG_DIR


def _read_int_env(name: str, default: int, minimum: int) -> int:
    """读取整数环境变量并做合法性校验。"""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigError(
            f"配置项 {name} 取值非法：{raw!r} 不是整数。请改为不小于 {minimum} 的整数。"
        ) from None
    if value < minimum:
        raise ConfigError(
            f"配置项 {name} 取值越界：{value} < {minimum}。请改为不小于 {minimum} 的整数。"
        )
    return value


def load_config(
    env_file: PathLike | None = ".env",
    *,
    required: bool = True,
) -> Settings:
    """从 `.env` 与环境变量加载配置。

    Args:
        env_file: .env 文件路径；传 `None` 跳过文件加载（仅用环境变量）。
        required: 为 True 时 api_key 缺失抛 `ConfigError`；为 False 时返回
            空 api_key（供只跑骨架/单测等不依赖 LLM 的场景使用）。

    Raises:
        ConfigError: 必需项缺失或取值非法。
    """
    if env_file is not None:
        # override=False：已存在的环境变量优先，.env 只填补空缺
        load_dotenv(dotenv_path=Path(env_file), override=False)

    # ---- api_key：必需（required=True 时） ----
    api_key = os.getenv(ENV_API_KEY) or os.getenv(ENV_API_KEY_FALLBACK)
    if api_key is None or api_key.strip() == "":
        if not required:
            api_key = ""
        else:
            raise ConfigError(
                f"缺少必需的配置项 {ENV_API_KEY}（或回退项 {ENV_API_KEY_FALLBACK}）。\n"
                f"请复制 .env.example 为 .env 并填写，或设置同名环境变量后再启动。"
            )

    log_level = (os.getenv(ENV_LOG_LEVEL) or DEFAULT_LOG_LEVEL).strip().upper()
    if log_level not in VALID_LOG_LEVELS:
        raise ConfigError(
            f"配置项 {ENV_LOG_LEVEL} 取值非法：{log_level!r}。"
            f"可选值：{', '.join(sorted(VALID_LOG_LEVELS))}。"
        )

    return Settings(
        api_key=api_key.strip(),
        base_url=(os.getenv(ENV_BASE_URL) or DEFAULT_BASE_URL).strip(),
        model=(os.getenv(ENV_MODEL) or DEFAULT_MODEL).strip(),
        max_rounds=_read_int_env(ENV_MAX_ROUNDS, DEFAULT_MAX_ROUNDS, minimum=1),
        context_threshold=_read_int_env(
            ENV_CONTEXT_THRESHOLD, DEFAULT_CONTEXT_THRESHOLD, minimum=1
        ),
        log_level=log_level,
        log_dir=(os.getenv(ENV_LOG_DIR) or DEFAULT_LOG_DIR).strip(),
    )


__all__ = [
    "Settings",
    "load_config",
    "ENV_API_KEY",
    "ENV_API_KEY_FALLBACK",
    "ENV_BASE_URL",
    "ENV_MODEL",
    "ENV_MAX_ROUNDS",
    "ENV_CONTEXT_THRESHOLD",
    "ENV_LOG_LEVEL",
    "ENV_LOG_DIR",
]
