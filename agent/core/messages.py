"""消息数据模型（Step 2 产出，**契约冻结点**）。

本模块定义的 `Message` / `ToolCall` / `FunctionCall` 将被 Step 3（工具 Schema）、
Step 4（主循环）、Step 5（会话 / 上下文）共同依赖，字段命名与结构按
**OpenAI Chat Completions 兼容格式**设计，后续只允许扩展、不做破坏性修改：

- role 取值：`system` / `user` / `assistant` / `tool`
- assistant 消息可携带 `tool_calls`（一个或多个工具调用请求）
- tool 消息（工具执行结果回填）必须带 `tool_call_id`，可选 `name`
- `FunctionCall.arguments` 始终是 **JSON 字符串**（而非 dict），与 OpenAI 线上格式一致；
  需要字典时用 `ToolCall.parsed_arguments()` 解析。

模型同时负责与 OpenAI 兼容 SDK 的线上字典格式互转：
- `to_openai_dict()`：发给 API（None 字段自动省略）
- `Message.from_openai()`：解析 API 响应（兼容 pydantic 对象与普通 dict）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

# ---- 角色常量（冻结，与 OpenAI 一致） ----
ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"
VALID_ROLES = frozenset({ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT, ROLE_TOOL})

TOOL_CALL_TYPE = "function"


def _as_plain_dict(obj: Any) -> dict[str, Any]:
    """把 pydantic 对象 / dataclass / 普通对象统一归一化为 dict。

    线上 SDK 返回的是 pydantic 模型（有 `model_dump`）；单测里可能用
    SimpleNamespace 等普通对象模拟；线上 dict 直接返回。
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        # pydantic v2：排除 None 以走与本模块一致的省略逻辑
        return model_dump(exclude_none=True)
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(obj)
    # 普通对象：按公开属性收集
    return {
        key: getattr(obj, key)
        for key in dir(obj)
        if not key.startswith("_") and not callable(getattr(obj, key))
    }


def _normalize_content(content: Any) -> str | None:
    """归一化 content：最小 Agent 只处理文本。

    若收到多模态 content 片段列表（[{type:text,text:...}, ...]），
    防御性地拼接其中的 text 片段；其余情况转成 str / None。
    """
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            part_dict = _as_plain_dict(part)
            if part_dict.get("type") in (None, "text") and part_dict.get("text") is not None:
                texts.append(str(part_dict["text"]))
        return "\n".join(texts) if texts else ""
    return str(content)


@dataclass
class FunctionCall:
    """一次函数调用的函数体：函数名 + JSON 字符串形式的参数。"""

    name: str
    arguments: str = ""  # 契约：始终为 JSON 字符串（空参数用 "" 或 "{}"）

    def parsed_arguments(self) -> dict[str, Any]:
        """把 arguments 解析为 dict；空字符串视为空参数。

        Raises:
            ValueError: arguments 不是合法 JSON 或不是 JSON 对象。
        """
        if self.arguments is None or self.arguments.strip() == "":
            return {}
        try:
            parsed = json.loads(self.arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"工具 {self.name!r} 的 arguments 不是合法 JSON：{self.arguments!r}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(
                f"工具 {self.name!r} 的 arguments 必须是 JSON 对象，得到 {type(parsed).__name__}"
            )
        return parsed

    def to_openai_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": self.arguments}


@dataclass
class ToolCall:
    """assistant 发起的一次工具调用请求（OpenAI 格式）。"""

    id: str
    function: FunctionCall
    type: str = TOOL_CALL_TYPE

    def to_openai_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "function": self.function.to_openai_dict(),
        }

    @classmethod
    def from_openai(cls, raw: Any) -> "ToolCall":
        """从 SDK 对象 / dict 构造 ToolCall。"""
        data = _as_plain_dict(raw)
        function_data = _as_plain_dict(data.get("function"))
        function = FunctionCall(
            name=str(function_data.get("name", "")),
            arguments="" if function_data.get("arguments") is None
            else str(function_data.get("arguments")),
        )
        return cls(
            id=str(data.get("id", "")),
            type=str(data.get("type", TOOL_CALL_TYPE)),
            function=function,
        )

    def parsed_arguments(self) -> dict[str, Any]:
        """便捷转发：解析内部函数参数。"""
        return self.function.parsed_arguments()


@dataclass
class Message:
    """一条对话消息（OpenAI Chat Completions 兼容结构，契约冻结）。

    Fields:
        role: system / user / assistant / tool 之一。
        content: 文本内容；assistant 携带 tool_calls 时可为 None。
        tool_calls: 仅 assistant 使用——请求调用的工具列表。
        tool_call_id: 仅 tool 消息使用——对应哪一次 assistant 工具调用。
        name: 可选名称（tool 消息回填工具名等场景）。
    """

    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise ValueError(
                f"非法 role={self.role!r}，合法值：{sorted(VALID_ROLES)}"
            )
        self.content = _normalize_content(self.content)
        if self.tool_calls is not None:
            self.tool_calls = [
                call if isinstance(call, ToolCall) else ToolCall.from_openai(call)
                for call in self.tool_calls
            ]

    # ---- 序列化为线上格式 ----
    def to_openai_dict(self) -> dict[str, Any]:
        """转为可直接传给 `chat.completions.create(messages=...)` 的 dict。

        None 字段一律省略，保持与 OpenAI 线上格式严格一致。
        """
        data: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            data["content"] = self.content
        if self.tool_calls is not None:
            data["tool_calls"] = [call.to_openai_dict() for call in self.tool_calls]
        if self.tool_call_id is not None:
            data["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            data["name"] = self.name
        return data

    # ---- 从线上响应解析 ----
    @classmethod
    def from_openai(cls, raw: Any) -> "Message":
        """从 SDK 响应 message（pydantic 对象 / dict）构造 Message。"""
        data = _as_plain_dict(raw)
        tool_calls_raw = data.get("tool_calls")
        tool_calls: list[ToolCall] | None = None
        if tool_calls_raw:
            tool_calls = [ToolCall.from_openai(item) for item in tool_calls_raw]
        return cls(
            role=str(data.get("role", ROLE_ASSISTANT)),
            content=_normalize_content(data.get("content")),
            tool_calls=tool_calls,
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
        )

    # ---- 语义化便捷构造器（冻结） ----
    @classmethod
    def system(cls, content: str, **kwargs: Any) -> "Message":
        return cls(role=ROLE_SYSTEM, content=content, **kwargs)

    @classmethod
    def user(cls, content: str, **kwargs: Any) -> "Message":
        return cls(role=ROLE_USER, content=content, **kwargs)

    @classmethod
    def assistant(
        cls,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        **kwargs: Any,
    ) -> "Message":
        return cls(
            role=ROLE_ASSISTANT, content=content, tool_calls=tool_calls, **kwargs
        )

    @classmethod
    def tool(
        cls,
        content: Any,
        tool_call_id: str,
        name: str | None = None,
        **kwargs: Any,
    ) -> "Message":
        """构造工具结果回填消息（content 统一字符串化）。"""
        return cls(
            role=ROLE_TOOL,
            content="" if content is None else str(content),
            tool_call_id=tool_call_id,
            name=name,
            **kwargs,
        )


def messages_to_openai(messages: Iterable[Message]) -> list[dict[str, Any]]:
    """批量序列化：Message 列表 -> OpenAI 线上 dict 列表。"""
    return [message.to_openai_dict() for message in messages]


__all__ = [
    "ROLE_SYSTEM",
    "ROLE_USER",
    "ROLE_ASSISTANT",
    "ROLE_TOOL",
    "VALID_ROLES",
    "TOOL_CALL_TYPE",
    "FunctionCall",
    "ToolCall",
    "Message",
    "messages_to_openai",
]
