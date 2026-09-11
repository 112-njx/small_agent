"""统一异常体系。

层级：AgentError（基类）
  ├── ConfigError   配置加载 / 校验错误
  ├── LLMError      LLM 调用 / 解析错误
  ├── ToolError     工具注册 / 调用 / 参数错误
  └── SessionError  会话与上下文管理错误

原则：Agent 内部所有可预期失败都应包装为 AgentError 的某个子类，
上层捕获 `AgentError` 即可覆盖全部业务异常，避免裸抛或依赖库异常泄漏到调用方。
"""

from __future__ import annotations


class AgentError(Exception):
    """Agent 业务异常基类。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class ConfigError(AgentError):
    """配置缺失、格式非法或取值越界。"""


class LLMError(AgentError):
    """LLM 客户端调用失败、超时或输出解析失败。"""


class ToolError(AgentError):
    """工具注册冲突、参数非法或工具执行异常。"""


class SessionError(AgentError):
    """会话不存在、隔离破坏或上下文管理失败。"""


__all__ = ["AgentError", "ConfigError", "LLMError", "ToolError", "SessionError"]
