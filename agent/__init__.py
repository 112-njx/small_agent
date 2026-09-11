"""small_agent —— 从零实现的最小可用 Agent。

包说明：
- config：配置加载（.env / 环境变量）
- errors：统一异常体系
- logging：统一日志（控制台 + 文件），为工具 trace 预留独立 logger
- core / llm / tools / session：后续步骤的模块落点
"""

__version__ = "0.1.0"

from agent.errors import (  # noqa: F401
    AgentError,
    ConfigError,
    LLMError,
    SessionError,
    ToolError,
)

__all__ = [
    "__version__",
    "AgentError",
    "ConfigError",
    "LLMError",
    "ToolError",
    "SessionError",
]
