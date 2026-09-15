"""LLMClient 单元测试：成功调用、参数透传、超时配置、指数退避重试与错误包装。

不发起任何真实网络请求：SDK 客户端通过依赖注入替换为 fake；退避 sleep 注入
为记录器，避免真实等待。SDK 异常实例用 openai 内置 vendored httpx 构造。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import openai
import pytest

from agent.config import Settings
from agent.core.messages import Message
from agent.errors import LLMError
from agent.llm.client import LLMClient

# openai 3.x 内置 vendored httpx（外部环境无独立 httpx）
from openai._httpx2 import httpx2


# ----------------------------------------------------------------------
# 辅助构造
# ----------------------------------------------------------------------
def _settings() -> Settings:
    return Settings(
        api_key="sk-test",
        base_url="https://test.example/v1",
        model="test-model",
    )


def _request() -> Any:
    return httpx2.Request("POST", "https://test.example/v1/chat/completions")


def _timeout_error() -> Exception:
    return openai.APITimeoutError(request=_request())


def _connection_error() -> Exception:
    return openai.APIConnectionError(message="conn reset", request=_request())


def _status_error(cls: type, status_code: int) -> Exception:
    return cls(
        "status error",
        response=httpx2.Response(status_code, request=_request()),
        body=None,
    )


def _assistant_response(
    content: str | None = "ok", tool_calls: list[dict] | None = None
) -> SimpleNamespace:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeCompletions:
    """按队列依次返回结果或抛出异常，并记录每次调用参数。"""

    def __init__(self, side_effects: list[Any]) -> None:
        self._side_effects = list(side_effects)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        effect = self._side_effects.pop(0)
        if isinstance(effect, BaseException):
            raise effect
        return effect


class FakeSDKClient:
    def __init__(self, side_effects: list[Any]) -> None:
        self.completions = FakeCompletions(side_effects)
        self.chat = SimpleNamespace(completions=self.completions)


def _make_client(side_effects: list[Any], **kwargs: Any) -> tuple[LLMClient, FakeCompletions]:
    fake = FakeSDKClient(side_effects)
    client = LLMClient(_settings(), client=fake, **kwargs)
    return client, fake.completions


# ----------------------------------------------------------------------
# 成功路径与参数透传
# ----------------------------------------------------------------------
def test_chat_success_returns_message() -> None:
    client, completions = _make_client([_assistant_response("你好")])

    result = client.chat(
        [Message.user("hi")],
        tools=[{"type": "function", "function": {"name": "f"}}],
        tool_choice="auto",
        temperature=0.2,
        max_tokens=100,
    )

    assert isinstance(result, Message)
    assert result.role == "assistant"
    assert result.content == "你好"

    sent = completions.calls[0]
    assert sent["model"] == "test-model"
    assert sent["messages"] == [{"role": "user", "content": "hi"}]
    assert sent["tools"][0]["function"]["name"] == "f"
    assert sent["tool_choice"] == "auto"
    assert sent["temperature"] == 0.2
    assert sent["max_tokens"] == 100  # extra 参数透传


def test_chat_response_with_native_tool_calls() -> None:
    client, _ = _make_client(
        [
            _assistant_response(
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": '{"expression": "1+1"}',
                        },
                    }
                ],
            )
        ]
    )

    result = client.chat([Message.user("算 1+1")])
    assert result.content is None
    assert result.tool_calls is not None
    assert result.tool_calls[0].function.name == "calculator"
    assert result.tool_calls[0].parsed_arguments() == {"expression": "1+1"}


def test_model_override_per_call() -> None:
    client, completions = _make_client([_assistant_response("x")])
    client.chat([Message.user("hi")], model="another-model")
    assert completions.calls[0]["model"] == "another-model"


# ----------------------------------------------------------------------
# 重试：指数退避
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "error_factory",
    [
        _timeout_error,
        _connection_error,
        lambda: _status_error(openai.RateLimitError, 429),
        lambda: _status_error(openai.InternalServerError, 503),
    ],
)
def test_retry_on_transient_errors_then_success(error_factory) -> None:
    sleeps: list[float] = []
    client, completions = _make_client(
        [error_factory(), error_factory(), _assistant_response("recovered")],
        max_retries=4,
        backoff_base=0.5,
        sleep=sleeps.append,
    )

    result = client.chat([Message.user("hi")])

    assert result.content == "recovered"
    assert len(completions.calls) == 3
    # 指数退避：0.5 * 2^0, 0.5 * 2^1
    assert sleeps == [0.5, 1.0]


def test_retries_exhausted_raises_llm_error() -> None:
    sleeps: list[float] = []
    client, completions = _make_client(
        [_timeout_error(), _timeout_error()],
        max_retries=2,
        backoff_base=0.01,
        sleep=sleeps.append,
    )

    with pytest.raises(LLMError) as exc_info:
        client.chat([Message.user("hi")])

    assert "2 次尝试后仍失败" in str(exc_info.value)
    assert len(completions.calls) == 2
    assert len(sleeps) == 1  # 最后一次失败后不再 sleep


def test_non_retryable_error_fails_fast() -> None:
    sleeps: list[float] = []
    client, completions = _make_client(
        [_status_error(openai.AuthenticationError, 401)],
        max_retries=3,
        sleep=sleeps.append,
    )

    with pytest.raises(LLMError) as exc_info:
        client.chat([Message.user("hi")])

    assert "不可重试" in str(exc_info.value)
    assert len(completions.calls) == 1  # 认证错误立即失败
    assert sleeps == []


def test_unexpected_exception_wrapped() -> None:
    client, _ = _make_client([RuntimeError("boom")], max_retries=2)
    with pytest.raises(LLMError):
        client.chat([Message.user("hi")])


# ----------------------------------------------------------------------
# 入参与构造校验
# ----------------------------------------------------------------------
def test_empty_messages_raises() -> None:
    client, completions = _make_client([_assistant_response("x")])
    with pytest.raises(LLMError):
        client.chat([])
    assert completions.calls == []  # 根本没有发出请求


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # 防止真实 .env / 环境变量补 key：load_config 在构造内被调用的路径才需要，
    # 这里显式传空 key settings 且不注入 client，直接校验
    with pytest.raises(LLMError):
        LLMClient(Settings(api_key="", base_url="u", model="m"))


def test_timeout_and_sdk_options_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("agent.llm.client.openai.OpenAI", FakeOpenAI)

    LLMClient(_settings(), timeout=12.5, max_retries=5, backoff_base=2.0)

    assert captured["api_key"] == "sk-test"
    assert captured["base_url"] == "https://test.example/v1"
    assert captured["timeout"] == 12.5
    # SDK 内部重试关闭，重试由 LLMClient 自己实现
    assert captured["max_retries"] == 0


def test_response_without_choices_raises() -> None:
    client, _ = _make_client([SimpleNamespace(choices=[])])
    with pytest.raises(LLMError):
        client.chat([Message.user("hi")])
