"""LLM 客户端：封装 OpenAI 兼容 Chat Completions 调用（DeepSeek 等同协议服务通用）。

职责：
- 从 Step 1 的 `load_config().Settings` 读取 api_key / base_url / model；
  DeepSeek 等兼容服务只需在 `.env` 配置 `LLM_BASE_URL` 与 `LLM_MODEL`，无需改代码。
- 通过官方 openai SDK 发起 `chat.completions.create`，支持 `tools`（function calling）参数。
- **超时**：构造时传入 timeout，透传给 SDK 的 HTTP 客户端。
- **指数退避重试**：对瞬时错误（超时 / 连接失败 / 429 / 5xx）按
  `backoff_base * 2**(attempt-1)` 退避后重试，最多 max_retries 次（含首次）。
- 一切失败统一包装为 Step 1 的 `LLMError`，不向调用方泄漏 SDK 内部异常。

SDK 自带的 `max_retries` 被显式置 0：重试策略（退避节奏、哪些错误可重试、日志）
由本类统一实现，避免双重重试且便于单测（sleep 可注入）。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Sequence

import openai

from agent.config import Settings, load_config
from agent.core.messages import Message, messages_to_openai
from agent.errors import LLMError
from agent.logging import get_logger

logger = get_logger("llm.client")

DEFAULT_TIMEOUT = 60.0  # 秒
DEFAULT_MAX_ATTEMPTS = 3  # 总尝试次数（含首次调用）
DEFAULT_BACKOFF_BASE = 1.0  # 首次重试前的基础退避秒数

# 可重试的瞬时错误（不同 SDK 版本下做存在性过滤，保证健壮性）
_RETRYABLE_NAMES = (
    "APITimeoutError",
    "APIConnectionError",
    "RateLimitError",
    "InternalServerError",
)


def _build_retryable_tuple() -> tuple[type[BaseException], ...]:
    classes = [
        getattr(openai, name)
        for name in _RETRYABLE_NAMES
        if isinstance(getattr(openai, name, None), type)
    ]
    return tuple(classes)


RETRYABLE_ERRORS: tuple[type[BaseException], ...] = _build_retryable_tuple()


class LLMClient:
    """OpenAI 兼容 Chat Completions 同步客户端。

    Args:
        settings: Step 1 的配置对象；为 None 时调用 `load_config()` 加载。
        timeout: 单次请求超时秒数，透传给 SDK。
        max_retries: 总尝试次数（含首次），最小为 1。
        backoff_base: 指数退避基数（秒），第 n 次重试前等待
            `backoff_base * 2**(n-1)`。
        sleep: 等待函数（可注入，单测中替换为假函数避免真实等待）。
        client: 已构造好的 SDK 客户端（依赖注入，单测注入 fake）；
            为 None 时按 settings 真实构造 `openai.OpenAI`。
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        sleep: Callable[[float], None] = time.sleep,
        client: Any | None = None,
    ) -> None:
        self.settings = settings if settings is not None else load_config()
        self.timeout = float(timeout)
        self.max_retries = max(1, int(max_retries))
        self.backoff_base = max(0.0, float(backoff_base))
        self._sleep = sleep
        self.model = self.settings.model

        if client is not None:
            self._client = client
        else:
            if not self.settings.api_key:
                raise LLMError(
                    "LLM API Key 为空：请在 .env 配置 LLM_API_KEY（或 OPENAI_API_KEY），"
                    "或显式传入 Settings / 已构造的 client。"
                )
            # SDK 内部重试关闭，重试统一由本类负责
            self._client = openai.OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                timeout=self.timeout,
                max_retries=0,
            )

    # ------------------------------------------------------------------
    # 核心调用
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        model: str | None = None,
        **extra: Any,
    ) -> Message:
        """发起一次 chat.completions 调用，返回解析后的 `Message`。

        Args:
            messages: 对话历史（本项目的 Message 模型）。
            tools: OpenAI 格式工具 schema 列表（Step 3 的 ToolRegistry 产出）。
            tool_choice: 工具选择策略（"auto" / "required" / 指定函数等）。
            temperature: 采样温度，None 表示用服务端默认值。
            model: 覆盖 settings.model 的单次调用模型名。
            **extra: 其他透传给 SDK 的参数（如 max_tokens）。

        Returns:
            assistant `Message`（可能携带 tool_calls）。

        Raises:
            LLMError: 入参非法、重试耗尽或遇到不可重试的 SDK 错误。
        """
        if not messages:
            raise LLMError("chat() 的 messages 不能为空，至少需要一条消息。")

        request_payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages_to_openai(messages),
        }
        if tools:
            request_payload["tools"] = tools
        if tool_choice is not None:
            request_payload["tool_choice"] = tool_choice
        if temperature is not None:
            request_payload["temperature"] = temperature
        request_payload.update(extra)

        response = self._request_with_retry(request_payload)
        return self._parse_response(response)

    # ------------------------------------------------------------------
    # 重试与错误包装
    # ------------------------------------------------------------------
    def _request_with_retry(self, payload: dict[str, Any]) -> Any:
        """带指数退避的请求循环，返回原始 SDK 响应。"""
        last_error: BaseException | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                return self._client.chat.completions.create(**payload)
            except RETRYABLE_ERRORS as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                delay = self.backoff_base * (2 ** (attempt - 1))
                logger.warning(
                    "LLM 请求遇到瞬时错误（第 %d/%d 次）：%s，%.2fs 后重试",
                    attempt,
                    self.max_retries,
                    type(exc).__name__,
                    delay,
                )
                self._sleep(delay)
            except openai.OpenAIError as exc:
                # 认证失败、参数非法等非瞬时错误：立即失败，不浪费重试
                logger.error("LLM 请求遇到不可重试错误：%s: %s", type(exc).__name__, exc)
                raise LLMError(
                    f"LLM 调用失败（不可重试，{type(exc).__name__}）：{exc}"
                ) from exc
            except LLMError:
                raise
            except Exception as exc:  # noqa: BLE001 - 兜底，杜绝裸泄 SDK 外异常
                logger.error("LLM 请求出现未预期异常：%s: %s", type(exc).__name__, exc)
                raise LLMError(
                    f"LLM 调用出现未预期异常（{type(exc).__name__}）：{exc}"
                ) from exc

        logger.error(
            "LLM 请求重试 %d 次后仍失败：%s",
            self.max_retries,
            type(last_error).__name__ if last_error else "UnknownError",
        )
        raise LLMError(
            f"LLM 调用在 {self.max_retries} 次尝试后仍失败"
            f"（{type(last_error).__name__ if last_error else 'UnknownError'}）："
            f"{last_error}"
        ) from last_error

    @staticmethod
    def _parse_response(response: Any) -> Message:
        """从 SDK 响应中取出首个 choice 的 message 并转为本项目模型。"""
        choices = getattr(response, "choices", None)
        if not choices:
            # 兼容 dict 形态响应
            if isinstance(response, dict) and response.get("choices"):
                choices = response["choices"]
            else:
                raise LLMError(f"LLM 响应缺少 choices：{response!r}")
        first_choice = choices[0]
        raw_message = (
            first_choice.get("message")
            if isinstance(first_choice, dict)
            else getattr(first_choice, "message", None)
        )
        if raw_message is None:
            raise LLMError(f"LLM 响应首个 choice 缺少 message：{first_choice!r}")
        return Message.from_openai(raw_message)


__all__ = [
    "LLMClient",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_BACKOFF_BASE",
    "RETRYABLE_ERRORS",
]
