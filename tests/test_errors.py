"""异常体系单元测试：层级关系与 message 语义。"""

from __future__ import annotations

import pytest

from agent.errors import (
    AgentError,
    ConfigError,
    LLMError,
    SessionError,
    ToolError,
)


def test_all_subclasses_of_agent_error() -> None:
    for cls in (ConfigError, LLMError, ToolError, SessionError):
        assert issubclass(cls, AgentError)


def test_agent_error_subclasses_exception() -> None:
    assert issubclass(AgentError, Exception)


def test_message_and_str() -> None:
    err = ConfigError("缺少必需配置项")
    assert err.message == "缺少必需配置项"
    assert str(err) == "缺少必需配置项"


def test_catch_via_base_class() -> None:
    with pytest.raises(AgentError):
        raise ToolError("工具执行失败")


def test_each_type_raiseable() -> None:
    cases = (
        (ConfigError, "配置错误"),
        (LLMError, "LLM 错误"),
        (ToolError, "工具错误"),
        (SessionError, "会话错误"),
    )
    for cls, msg in cases:
        with pytest.raises(cls):
            raise cls(msg)


def test_error_is_exception_instance() -> None:
    assert isinstance(LLMError("x"), Exception)
    assert isinstance(SessionError("x"), AgentError)
