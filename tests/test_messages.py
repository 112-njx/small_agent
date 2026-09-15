"""消息模型单元测试（契约冻结点）。

覆盖：角色校验、便捷构造器、OpenAI 线上格式序列化（None 省略 / arguments
保持 JSON 字符串）、SDK 对象与 dict 的反向解析、参数解析辅助方法。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.core.messages import (
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_TOOL,
    ROLE_USER,
    FunctionCall,
    Message,
    ToolCall,
    messages_to_openai,
)


# ----------------------------------------------------------------------
# 构造与角色校验
# ----------------------------------------------------------------------
def test_convenience_constructors() -> None:
    assert Message.system("sys").role == ROLE_SYSTEM
    assert Message.user("hi").role == ROLE_USER
    assistant = Message.assistant("thinking")
    assert assistant.role == ROLE_ASSISTANT and assistant.content == "thinking"
    tool_msg = Message.tool("42", "call_1", name="calculator")
    assert tool_msg.role == ROLE_TOOL
    assert tool_msg.tool_call_id == "call_1"
    assert tool_msg.name == "calculator"


def test_invalid_role_raises() -> None:
    with pytest.raises(ValueError):
        Message(role="robot", content="x")  # type: ignore[arg-type]


def test_tool_message_stringifies_content() -> None:
    assert Message.tool(123, "call_1").content == "123"
    assert Message.tool(None, "call_1").content == ""


# ----------------------------------------------------------------------
# 序列化为 OpenAI 线上格式
# ----------------------------------------------------------------------
def test_to_openai_dict_omits_none_fields() -> None:
    data = Message.user("hello").to_openai_dict()
    assert data == {"role": ROLE_USER, "content": "hello"}
    assert "tool_calls" not in data
    assert "tool_call_id" not in data
    assert "name" not in data


def test_assistant_tool_calls_wire_format() -> None:
    call = ToolCall(
        id="call_abc",
        function=FunctionCall(name="calculator", arguments='{"expression": "1+1"}'),
    )
    msg = Message.assistant(content=None, tool_calls=[call])
    data = msg.to_openai_dict()

    assert data["role"] == ROLE_ASSISTANT
    assert "content" not in data  # None 省略
    assert data["tool_calls"] == [
        {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "calculator", "arguments": '{"expression": "1+1"}'},
        }
    ]
    # 契约：arguments 在线上格式里始终是字符串
    assert isinstance(data["tool_calls"][0]["function"]["arguments"], str)


def test_tool_result_wire_format() -> None:
    data = Message.tool("result", "call_1", name="search").to_openai_dict()
    assert data == {
        "role": ROLE_TOOL,
        "content": "result",
        "tool_call_id": "call_1",
        "name": "search",
    }


def test_messages_to_openai_batch() -> None:
    batch = messages_to_openai(
        [Message.system("s"), Message.user("u"), Message.tool("r", "id_1")]
    )
    assert [item["role"] for item in batch] == ["system", "user", "tool"]
    assert batch[2]["tool_call_id"] == "id_1"


# ----------------------------------------------------------------------
# 从 SDK 响应反向解析
# ----------------------------------------------------------------------
def test_from_openai_dict_with_tool_calls() -> None:
    raw = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_x",
                "type": "function",
                "function": {"name": "todo", "arguments": '{"title": "write tests"}'},
            },
            {
                "id": "call_y",
                "type": "function",
                "function": {"name": "calculator", "arguments": "{}"},
            },
        ],
    }
    msg = Message.from_openai(raw)

    assert msg.role == ROLE_ASSISTANT
    assert msg.content is None
    assert len(msg.tool_calls) == 2
    assert msg.tool_calls[0].id == "call_x"
    assert msg.tool_calls[0].function.name == "todo"
    assert msg.tool_calls[0].parsed_arguments() == {"title": "write tests"}
    assert msg.tool_calls[1].parsed_arguments() == {}


def test_from_openai_plain_text_dict() -> None:
    msg = Message.from_openai({"role": "assistant", "content": "你好"})
    assert msg.content == "你好"
    assert msg.tool_calls is None


def test_from_openai_sdk_like_nested_objects() -> None:
    """模拟 SDK 返回的 pydantic 对象（属性访问 + 嵌套 function 对象）。"""
    raw = SimpleNamespace(
        role="assistant",
        content="calling",
        tool_calls=[
            SimpleNamespace(
                id="call_o",
                type="function",
                function=SimpleNamespace(name="search", arguments='{"q": "x"}'),
            )
        ],
    )
    msg = Message.from_openai(raw)
    assert msg.content == "calling"
    assert msg.tool_calls[0].function.name == "search"
    assert msg.tool_calls[0].parsed_arguments() == {"q": "x"}


def test_post_init_coerces_dict_tool_calls() -> None:
    """构造时直接传 dict 形态 tool_calls 也会被归一化为 ToolCall。"""
    msg = Message(
        role=ROLE_ASSISTANT,
        tool_calls=[
            {
                "id": "call_z",
                "type": "function",
                "function": {"name": "calculator", "arguments": '{"a": 1}'},
            }
        ],
    )
    assert isinstance(msg.tool_calls[0], ToolCall)
    assert msg.tool_calls[0].id == "call_z"
    assert msg.tool_calls[0].function.parsed_arguments() == {"a": 1}


# ----------------------------------------------------------------------
# arguments 解析辅助
# ----------------------------------------------------------------------
def test_parsed_arguments_variants() -> None:
    assert FunctionCall("t", "").parsed_arguments() == {}
    assert FunctionCall("t", "  ").parsed_arguments() == {}
    assert FunctionCall("t", '{"k": [1, 2]}').parsed_arguments() == {"k": [1, 2]}


def test_parsed_arguments_invalid_json_raises() -> None:
    with pytest.raises(ValueError):
        FunctionCall("t", "{not json").parsed_arguments()


def test_parsed_arguments_non_object_raises() -> None:
    with pytest.raises(ValueError):
        FunctionCall("t", "[1, 2, 3]").parsed_arguments()


def test_roundtrip_preserves_arguments_string() -> None:
    raw = {
        "role": "assistant",
        "tool_calls": [
            {"id": "c1", "function": {"name": "f", "arguments": '{"x": 1}'}}
        ],
    }
    msg = Message.from_openai(raw)
    wire = msg.to_openai_dict()
    assert wire["tool_calls"][0]["function"]["arguments"] == '{"x": 1}'
