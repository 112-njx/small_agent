"""Parser 单元测试：原生工具调用、文本 JSON 兜底、纯文本回答、畸形输出降级。

同时覆盖：字段别名、参数归一化（arguments 保持 JSON 字符串）、思考过程抽取、
JSON 形态最终答案、空内容等边界。
"""

from __future__ import annotations

import json

import pytest

from agent.core.messages import FunctionCall, Message, ToolCall
from agent.llm.parser import FALLBACK_ID_PREFIX, Parser, parse_message


@pytest.fixture
def parser() -> Parser:
    return Parser()


def _native_message(
    content: str | None = "我来调用工具",
    calls: list[ToolCall] | None = None,
) -> Message:
    if calls is None:
        calls = [ToolCall("call_1", FunctionCall("calculator", '{"expression": "1+1"}'))]
    return Message.assistant(content=content, tool_calls=calls)


# ----------------------------------------------------------------------
# 路径 1：原生 function calling
# ----------------------------------------------------------------------
def test_native_tool_calls(parser: Parser) -> None:
    result = parser.parse(_native_message())

    assert result.is_tool_call
    assert not result.is_final
    assert result.thought == "我来调用工具"
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.id == "call_1"
    assert call.function.name == "calculator"
    assert call.function.arguments == '{"expression": "1+1"}'
    assert result.final_answer is None


def test_native_tool_calls_without_content(parser: Parser) -> None:
    result = parser.parse(_native_message(content=None))
    assert result.is_tool_call
    assert result.thought is None


def test_native_multiple_tool_calls(parser: Parser) -> None:
    msg = _native_message(
        content=None,
        calls=[
            ToolCall("c1", FunctionCall("a", "{}")),
            ToolCall("c2", FunctionCall("b", '{"x": 1}')),
        ],
    )
    result = parser.parse(msg)
    assert [c.function.name for c in result.tool_calls] == ["a", "b"]


# ----------------------------------------------------------------------
# 路径 2：文本内 ```json 代码块兜底
# ----------------------------------------------------------------------
def test_fenced_json_tool_call(parser: Parser) -> None:
    text = '```json\n{"name": "calculator", "arguments": {"expression": "2*3"}}\n```'
    result = parser.parse_text(text)

    assert result.is_tool_call
    call = result.tool_calls[0]
    assert call.function.name == "calculator"
    assert call.id.startswith(FALLBACK_ID_PREFIX)  # 兜底路径自动生成 id
    assert call.type == "function"
    # 契约：arguments 归一化为 JSON 字符串
    assert isinstance(call.function.arguments, str)
    assert json.loads(call.function.arguments) == {"expression": "2*3"}


def test_fenced_json_with_prose_becomes_thought(parser: Parser) -> None:
    text = (
        "我需要先计算一下乘积。\n"
        '```json\n{"name": "calculator", "arguments": {"expression": "2*3"}}\n```'
    )
    result = parser.parse_text(text)

    assert result.is_tool_call
    assert result.thought == "我需要先计算一下乘积。"
    assert result.tool_calls[0].function.name == "calculator"


def test_fenced_json_with_explicit_thought_field(parser: Parser) -> None:
    text = (
        "外围散文\n"
        '```json\n{"thought": "内部思考", "name": "search", '
        '"arguments": {"q": "weather"}}\n```'
    )
    result = parser.parse_text(text)
    assert result.is_tool_call
    assert result.thought == "内部思考"  # 显式 thought 字段优先于外围散文


def test_bare_json_tool_call(parser: Parser) -> None:
    result = parser.parse_text('前缀说明 {"name": "todo", "arguments": {"title": "买水"}}')
    assert result.is_tool_call
    assert result.tool_calls[0].function.name == "todo"
    assert json.loads(result.tool_calls[0].function.arguments) == {"title": "买水"}
    assert result.thought == "前缀说明"


def test_field_aliases_tool_and_parameters(parser: Parser) -> None:
    result = parser.parse_text('{"tool": "search", "parameters": {"q": "x"}}')
    assert result.is_tool_call
    assert result.tool_calls[0].function.name == "search"
    assert json.loads(result.tool_calls[0].function.arguments) == {"q": "x"}


def test_arguments_as_json_string_normalized(parser: Parser) -> None:
    # arguments 本身是 JSON 字符串：解析后规范化重序列化
    result = parser.parse_text('{"name": "f", "arguments": "{\\"k\\": 1}"}')
    assert result.is_tool_call
    assert json.loads(result.tool_calls[0].function.arguments) == {"k": 1}


def test_arguments_as_plain_string_wrapped(parser: Parser) -> None:
    result = parser.parse_text('{"name": "f", "arguments": "oops"}')
    assert result.is_tool_call
    # 非 JSON 字符串包成合法 JSON 字符串，契约不破
    assert json.loads(result.tool_calls[0].function.arguments) == "oops"


def test_arguments_none_defaults_empty_object(parser: Parser) -> None:
    result = parser.parse_text('{"name": "f"}')
    assert result.tool_calls[0].function.arguments == "{}"


def test_json_array_of_tool_calls(parser: Parser) -> None:
    text = (
        '```json\n[{"name": "a", "arguments": {}}, '
        '{"name": "b", "arguments": {"v": 2}}]\n```'
    )
    result = parser.parse_text(text)
    assert [c.function.name for c in result.tool_calls] == ["a", "b"]
    assert json.loads(result.tool_calls[1].function.arguments) == {"v": 2}


# ----------------------------------------------------------------------
# 纯文本回答
# ----------------------------------------------------------------------
def test_plain_text_is_final_answer(parser: Parser) -> None:
    result = parser.parse_text("今天郑州晴，气温 26 度。")
    assert result.is_final
    assert result.final_answer == "今天郑州晴，气温 26 度。"
    assert result.tool_calls == []
    assert result.thought is None


def test_final_answer_label_stripped(parser: Parser) -> None:
    result = parser.parse_text("最终答案：42")
    assert result.is_final
    assert result.final_answer == "42"


def test_thought_tag_extracted_for_plain_answer(parser: Parser) -> None:
    result = parser.parse_text("<thought>先推理一下</thought>\n最终答案是 7。")
    assert result.thought == "先推理一下"
    assert result.final_answer == "最终答案是 7。"


def test_thought_label_extracted(parser: Parser) -> None:
    result = parser.parse_text("Thought: 我先确认问题\n\n答案是 OK。")
    assert result.thought == "我先确认问题"
    assert result.final_answer == "答案是 OK。"


def test_json_form_final_answer(parser: Parser) -> None:
    result = parser.parse_text('```json\n{"thought": "推完了", "answer": "等于 3"}\n```')
    assert result.is_final
    assert result.thought == "推完了"
    assert result.final_answer == "等于 3"


def test_unbalanced_braces_fall_back_to_text(parser: Parser) -> None:
    result = parser.parse_text("这是一段包含 { 未闭合花括号的普通文本")
    assert result.is_final
    assert result.final_answer == "这是一段包含 { 未闭合花括号的普通文本"


def test_valid_json_but_unrecognized_keys_degrades(parser: Parser) -> None:
    result = parser.parse_text('```json\n{"foo": 1, "bar": 2}\n```')
    assert result.is_final
    assert "foo" in result.final_answer


# ----------------------------------------------------------------------
# 畸形输出：降级不中断
# ----------------------------------------------------------------------
def test_malformed_fenced_json_degrades_to_text(parser: Parser) -> None:
    raw = "说明：\n```json\n{name: calculator, arguments: }\n```"
    result = parser.parse_text(raw)
    # 不抛异常，整体作为普通文本回答
    assert result.is_final
    assert result.final_answer == raw


def test_empty_content(parser: Parser) -> None:
    result = parser.parse(Message.assistant(content=""))
    assert result.is_final
    assert result.final_answer == ""
    assert result.tool_calls == []


def test_none_content(parser: Parser) -> None:
    result = parser.parse(Message.assistant(content=None))
    assert result.final_answer == ""


# ----------------------------------------------------------------------
# 模块级入口
# ----------------------------------------------------------------------
def test_module_level_parse_message() -> None:
    result = parse_message(Message.assistant("直接回答"))
    assert result.final_answer == "直接回答"
