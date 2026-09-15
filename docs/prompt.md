# 新 Agent 第二轮开发提示词（Step 2：LLM 通信层）

## 你是谁
你是 small_agent 项目的开发 Agent。项目目标：**从零实现一个最小可用 Agent**——核心 Agent Runtime 自行实现，不依赖 langgraph / openhands 等现成框架；允许使用 AI 工具辅助开发（含核心 Runtime）。完整需求见项目根目录 `readme.md`。

## 环境与现状
- 项目根目录：`D:\small_agent`（Windows / PowerShell 环境）
- 开发规划：`docs/roadmap.md`（拓扑版；**本轮只做 Step 2**，严格依赖 Step 1）
- Git：已连接 GitHub，`origin = https://github.com/112-njx/small_agent.git`，分支 `main`
- **Step 1 已完成并验收**：`agent/{errors,config,logging}.py`、`agent/__main__.py`（空壳）、`pyproject.toml`（openai / python-dotenv / pytest）、`.env.example`、`tests/`（26 passed）。
- 对 Step 1 已有模块**只使用不修改**（配置用 `load_config().Settings`，日志用 `get_logger()`，异常用 `errors` 体系）；确需改动须在回报中说明理由。

## 本轮任务：Step 2 LLM 通信层（消息模型 + 客户端 + 输出解析）
目标：打通真实 LLM API 调用并具备可靠输出解析，为 Agent 自主决策打基础。

1. **`agent/core/messages.py`**：`Message` 数据模型（role / content / tool_calls / tool_call_id / name 等）。
   ⚠️ **契约冻结点**：该模型将被 Step 3（工具 Schema）、Step 4（主循环）、Step 5（会话/上下文）依赖，字段按 **OpenAI 兼容格式**设计（assistant 可携带 tool_calls；tool 消息带 tool_call_id；arguments 为 JSON 字符串），命名保持稳定。
2. **`agent/llm/client.py`**：`LLMClient` 调用真实 OpenAI 兼容 API（openai SDK，chat.completions + tools 参数）；配置从 `load_config()` 的 `Settings` 读取；支持超时与指数退避重试；调用失败抛 `LLMError`。
3. **`agent/llm/parser.py`**：`Parser` 输出解析——
   - 原生 function calling 响应（tool_calls 字段）
   - 文本内 JSON 兜底（如 ```json 代码块）
   - 提取三类产物：**思考过程 / 工具调用 / 最终答案**
   - 解析失败降级为普通文本回答并记录日志（不中断流程）

**产出文件**：`agent/core/messages.py`、`agent/llm/client.py`、`agent/llm/parser.py`

## 验收标准
- 解析器单测覆盖（mock 响应）：原生工具调用、文本 JSON 兜底、纯文本回答、畸形输出
- 客户端支持超时 / 重试参数
- `pytest` 全绿（既有 26 个用例不回归）；真实 API 冒烟测试可选（需 `.env` 配 key）

## 开发约定
- 每个功能点写单元测试，`pytest` 全绿后再提交
- **编码记录**追加到 `docs/code.md`（第 2 轮）；bug 及修复写入 `docs/bug.md`（格式见两文件头部说明）
- 完成后提交：`git add -A && git commit -m "feat: step2 llm layer" && git push`

## 完成后回报
交付物清单、pytest 结果、commit hash、遗留问题。
