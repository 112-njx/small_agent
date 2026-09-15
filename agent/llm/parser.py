"""LLM 输出解析器：从模型响应中提取「思考过程 / 工具调用 / 最终答案」三类产物。

两条解析路径，优先级从高到低：

1. **原生 function calling**：assistant 消息自带 `tool_calls` 字段（OpenAI 兼容
   服务的标准通道，DeepSeek 同样支持），此时 `content`（若有）作为思考过程。
2. **文本内 JSON 兜底**：模型未走原生通道时，从文本中识别工具调用——
   - ```json 代码块（首选）/ 裸 JSON 对象（花括号配平扫描，容忍前后散文）；
   - 字段名兼容常见写法：name/tool/tool_name/function，
     arguments/parameters/args/params，thought/thinking/reasoning；
   - 支持单次对象与对象数组两种形态。

降级原则（不中断主流程）：
- 任何疑似 JSON 但解析失败的「畸形输出」，以及无法识别结构的内容，
  一律降级为**普通文本最终答案**，并记录 warning 日志。
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

from agent.core.messages import FunctionCall, Message, ToolCall
from agent.logging import get_logger

logger = get_logger("llm.parser")

FALLBACK_ID_PREFIX = "call_fallback_"

# ```json ... ``` 或 ``` ... ``` 代码块
_FENCED_BLOCK_RE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.DOTALL)
# <thought>...</thought> 思考标签
_THOUGHT_TAG_RE = re.compile(
    r"<thought\s*>(.*?)</thought\s*>", re.DOTALL | re.IGNORECASE
)
# Thought: ... / 思考：... 行内标签（截到空行 / 最终答案标记 / 文末）
_THOUGHT_LABEL_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:Thought|思考过程?)[ \t]*[:：][ \t]*"
    r"(.*?)(?=\n[ \t]*\n|(?:Final[ _]Answer|最终答案)[ \t]*[:：]|$)",
    re.DOTALL,
)
# 最终答案前缀标记
_FINAL_LABEL_RE = re.compile(
    r"^\s*(?:Final[ _]Answer|最终答案)[ \t]*[:：]\s*", re.IGNORECASE
)

# JSON 兜底格式的字段别名
_NAME_KEYS = ("name", "tool", "tool_name", "function", "function_name")
_ARGS_KEYS = ("arguments", "args", "parameters", "params")
_THOUGHT_KEYS = ("thought", "thinking", "reasoning", "思考", "思考过程")
_ANSWER_KEYS = (
    "answer",
    "final_answer",
    "final",
    "response",
    "result",
    "output",
    "content",
)


@dataclass
class ParseResult:
    """解析产物：三类输出互有侧重（工具调用与最终答案互斥，思考过程可共存）。"""

    thought: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    final_answer: str | None = None

    @property
    def is_tool_call(self) -> bool:
        """本次解析是否得到工具调用请求。"""
        return bool(self.tool_calls)

    @property
    def is_final(self) -> bool:
        """本次解析是否得到面向用户的最终答案。"""
        return not self.tool_calls and self.final_answer is not None


class Parser:
    """LLM 输出解析器（无状态，可复用单例）。

    Args:
        fallback_id_prefix: 文本 JSON 兜底路径生成的工具调用 id 前缀。
    """

    def __init__(self, fallback_id_prefix: str = FALLBACK_ID_PREFIX) -> None:
        self.fallback_id_prefix = fallback_id_prefix

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------
    def parse(self, message: Message) -> ParseResult:
        """解析一条 assistant Message，返回 ParseResult。"""
        # 路径 1：原生 function calling
        if message.tool_calls:
            thought = message.content.strip() if message.content else None
            logger.debug(
                "原生 tool_calls：%d 个工具调用", len(message.tool_calls)
            )
            return ParseResult(
                thought=thought, tool_calls=list(message.tool_calls)
            )

        content = message.content
        if content is None or content.strip() == "":
            logger.warning("LLM 返回空内容（无 tool_calls 且 content 为空），降级为空文本回答")
            return ParseResult(thought=None, tool_calls=[], final_answer=content or "")

        return self.parse_text(content)

    def parse_text(self, text: str) -> ParseResult:
        """解析纯文本输出（兜底路径 + 纯文本回答）。"""
        raw = text
        # 1) 先抽行内思考标记，剩余正文继续参与 JSON 识别
        inline_thought, remainder = self._extract_inline_thought(raw)

        # 2) 定位 JSON 候选串（代码块优先，其次花括号配平扫描）
        candidate = self._locate_json_candidate(remainder)
        if candidate is None:
            # 无 JSON：纯文本最终答案
            return self._plain_text_result(inline_thought, remainder, raw)

        # 3) 解析 JSON；畸形 JSON 走降级
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "疑似工具调用 JSON 但解析失败，降级为普通文本回答：%s；原文片段：%r",
                exc,
                candidate[:200],
            )
            return ParseResult(thought=inline_thought, final_answer=raw)

        # 4) 归一化为「条目列表」
        if isinstance(parsed, dict):
            items = [parsed]
        elif isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
            items = parsed
        else:
            logger.info("JSON 结构不是工具调用对象，按普通文本处理：%r", candidate[:200])
            return self._plain_text_result(inline_thought, remainder, raw)

        tool_calls: list[ToolCall] = []
        json_thought: str | None = None
        json_answer: Any = None  # noqa: UP037 - 取值类型不定，最终统一字符串化

        for item in items:
            name = self._pick_first(item, _NAME_KEYS)
            # thought 字段可能与 name 共存于同一对象，先抽取再 continue
            thought_value = self._pick_first(item, _THOUGHT_KEYS)
            if thought_value is not None and json_thought is None:
                json_thought = self._stringify(thought_value)
            if name is not None:
                tool_calls.append(self._build_fallback_tool_call(str(name), item))
                continue
            answer_value = self._pick_first(item, _ANSWER_KEYS)
            if answer_value is not None and json_answer is None:
                json_answer = answer_value

        thought = json_thought or inline_thought

        # 5a) 工具调用优先
        if tool_calls:
            if thought is None:
                # JSON 外的散文作为思考过程
                prose = self._strip_json_fragments(remainder).strip()
                thought = prose or None
            logger.debug(
                "文本 JSON 兜底解析出 %d 个工具调用", len(tool_calls)
            )
            return ParseResult(thought=thought, tool_calls=tool_calls)

        # 5b) JSON 形式的最终答案
        if json_answer is not None:
            final = self._stringify(json_answer)
            return ParseResult(thought=thought, final_answer=final)

        # 5c) JSON 合法但语义不可识别：降级普通文本
        logger.info("JSON 缺少工具名 / 答案字段，按普通文本处理：%r", candidate[:200])
        return self._plain_text_result(inline_thought, remainder, raw)

    # ------------------------------------------------------------------
    # 文本内辅助方法
    # ------------------------------------------------------------------
    def _extract_inline_thought(self, text: str) -> tuple[str | None, str]:
        """抽取 <thought> 标签与 Thought:/思考： 行标签，返回 (思考, 剩余文本)。"""
        pieces: list[str] = []
        remainder = text

        tag_matches = list(_THOUGHT_TAG_RE.finditer(remainder))
        if tag_matches:
            pieces.extend(m.group(1).strip() for m in tag_matches)
            remainder = _THOUGHT_TAG_RE.sub("", remainder)

        label_matches = list(_THOUGHT_LABEL_RE.finditer(remainder))
        if label_matches:
            pieces.extend(m.group(1).strip() for m in label_matches)
            remainder = _THOUGHT_LABEL_RE.sub("", remainder)

        thought = "\n".join(piece for piece in pieces if piece) or None
        return thought, remainder

    def _locate_json_candidate(self, text: str) -> str | None:
        """定位 JSON 候选串：先代码块，再裸花括号配平扫描。"""
        fenced = _FENCED_BLOCK_RE.search(text)
        if fenced:
            candidate = fenced.group(1).strip()
            if candidate:
                return candidate

        return self._scan_balanced_json(text)

    @staticmethod
    def _scan_balanced_json(text: str) -> str | None:
        """从首个 `{`/`[` 起做配平扫描（识别字符串与转义），返回完整 JSON 子串。"""
        start = min(
            (idx for idx in (text.find("{"), text.find("[")) if idx != -1),
            default=-1,
        )
        if start == -1:
            return None
        open_char = text[start]
        close_char = "}" if open_char == "{" else "]"
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
        return None  # 括号未配平

    def _build_fallback_tool_call(self, name: str, item: dict) -> ToolCall:
        """把文本 JSON 中的一个调用条目构造为 ToolCall（id 自动生成）。"""
        raw_args = self._pick_first(item, _ARGS_KEYS)
        arguments = self._normalize_arguments(raw_args)
        call_id = f"{self.fallback_id_prefix}{uuid.uuid4().hex[:12]}"
        return ToolCall(
            id=call_id,
            type="function",
            function=FunctionCall(name=name, arguments=arguments),
        )

    @staticmethod
    def _normalize_arguments(raw_args: Any) -> str:
        """把任意形态的参数归一化为契约要求的 JSON 字符串。"""
        if raw_args is None:
            return "{}"
        if isinstance(raw_args, str):
            stripped = raw_args.strip()
            if stripped == "":
                return "{}"
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                # 非 JSON 字符串：包成合法 JSON 字符串，保证契约不破
                return json.dumps(stripped, ensure_ascii=False)
            return json.dumps(parsed, ensure_ascii=False)
        return json.dumps(raw_args, ensure_ascii=False)

    @staticmethod
    def _strip_json_fragments(text: str) -> str:
        """移除文本中的代码块与裸 JSON 片段，只留散文（用作思考过程）。"""
        cleaned = _FENCED_BLOCK_RE.sub("", text)
        bare = Parser._scan_balanced_json(cleaned)
        if bare is not None:
            cleaned = cleaned.replace(bare, "")
        return cleaned

    def _plain_text_result(
        self, inline_thought: str | None, remainder: str, raw: str
    ) -> ParseResult:
        """构造纯文本最终答案（去掉思考标签与代码块围栏后的正文）。"""
        body = self._strip_json_fragments(remainder).strip() or raw.strip()
        final = _FINAL_LABEL_RE.sub("", body).strip()
        return ParseResult(thought=inline_thought, final_answer=final)

    # ------------------------------------------------------------------
    # 小工具
    # ------------------------------------------------------------------
    @staticmethod
    def _pick_first(item: dict, keys: tuple[str, ...]) -> Any:
        """按候选 key 顺序取第一个存在且非 None 的值。"""
        for key in keys:
            if key in item and item[key] is not None:
                return item[key]
        return None

    @staticmethod
    def _stringify(value: Any) -> str:
        """JSON 答案字段字符串化（dict/list 用紧凑 JSON，保留中文）。"""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)


def parse_message(message: Message) -> ParseResult:
    """模块级便捷函数：用默认 Parser 解析单条消息。"""
    return Parser().parse(message)


__all__ = ["ParseResult", "Parser", "parse_message", "FALLBACK_ID_PREFIX"]
