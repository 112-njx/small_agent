# Agent 编码记录

> 用途：记录每一轮 agent 开发的编码情况，由开发 Agent 在每轮完成后**追加**记录。

## 记录格式
- 轮次 / 日期 / 任务（对应 roadmap 步骤）
- 产出文件清单
- 测试与验证结果（pytest）
- commit hash
- 遗留问题

---

## 开发记录

### 第 0 轮（2026-09-11）· 规划期
- 内容：解读 readme.md 要求，编写开发路线图（7 步均分 + 拓扑依赖分析）
- 产出：`docs/roadmap.md`
- 提交：`869a5f5`（docs: rewrite roadmap with topology）

### 第 1 轮（2026-09-11）· Step 1 项目骨架与基础设施 ✅
- 内容：建立工程骨架（目录 / 配置 / 日志 / 异常体系）
- 产出文件清单：
  - `pyproject.toml`：依赖声明（openai、python-dotenv、pytest dev 组）+ pytest 配置（testpaths、pythonpath）
  - `.env.example`：环境变量模板（LLM_API_KEY / LLM_BASE_URL / LLM_MODEL / AGENT_MAX_ROUNDS / AGENT_CONTEXT_THRESHOLD / LOG_LEVEL / AGENT_LOG_DIR）
  - `agent/errors.py`：AgentError 基类 + ConfigError / LLMError / ToolError / SessionError
  - `agent/config.py`：load_config()（.env → 环境变量，后者优先；缺 key 抛可读 ConfigError；required=False 支持无 key 场景）+ Settings dataclass
  - `agent/logging.py`：setup_logging()（控制台 + RotatingFileHandler 写入 logs/，幂等），预留 `agent.tools` / `agent.session` 独立 logger
  - `agent/__main__.py`：`python -m agent` 空壳入口
  - `agent/{core,llm,tools,session}/__init__.py`：后续步骤落点占位
  - `tests/{test_config,test_errors,test_logging}.py`：26 个单测
  - `logs/.gitkeep`；`.gitignore` 修复（见 docs/bug.md）
- 测试与验证结果：`pytest` **26 passed**；`python -m agent` 退出码 0；冒烟验证 `logs/agent.log` 正常落盘、缺 LLM_API_KEY 时报可读 ConfigError
- commit hash：见本轮提交
- 遗留问题：
  - `python -m agent` 目前仅空壳；真实 LLM 调用需在 Step 2 接入后、配置 `.env` 方可运行
  - 上下文阈值暂为静态配置（AGENT_CONTEXT_THRESHOLD=8000），实际按 token 估算的策略留待 Step 5 定义

### 第 2 轮（2026-09-15）· Step 2 LLM 通信层 ✅
- 内容：消息数据模型（契约冻结点）+ LLM 客户端（OpenAI 兼容 / DeepSeek 同协议）+ 输出解析器
- 产出文件清单：
  - `agent/core/messages.py`：
    - `FunctionCall`（name + arguments，**arguments 契约为 JSON 字符串**，`parsed_arguments()` 解析）
    - `ToolCall`（id / type="function" / function）、`Message`（role / content / tool_calls / tool_call_id / name）
    - 角色常量 system/user/assistant/tool + 非法 role 校验
    - `to_openai_dict()`（None 字段省略）、`messages_to_openai()` 批量序列化
    - `Message.from_openai()` 反向解析（兼容 SDK pydantic 对象、普通对象与 dict；多模态 content 片段防御性拼接）
    - 便捷构造器 `Message.system/user/assistant/tool`；构造时 dict 形态 tool_calls 自动归一化
  - `agent/llm/client.py`：
    - `LLMClient`：配置取自 `load_config().Settings`（DeepSeek 等只需改 `.env` 的 LLM_BASE_URL / LLM_MODEL）
    - 官方 openai SDK `chat.completions.create`，支持 tools / tool_choice / temperature 及额外参数透传
    - 超时 timeout 透传 SDK；SDK 内置 max_retries 显式置 0，重试由本类统一实现
    - 指数退避：对 APITimeoutError / APIConnectionError / RateLimitError(429) / InternalServerError(5xx)
      按 `backoff_base * 2**(n-1)` 退避重试；认证错误等不可重试错误立即失败
    - sleep 与 SDK client 均可注入（便于单测、无真实等待 / 无真实网络）；一切失败统一包装为 `LLMError`
  - `agent/llm/parser.py`：
    - `ParseResult`（thought / tool_calls / final_answer + is_tool_call / is_final）、`Parser.parse(Message)` / `parse_text(str)`
    - 路径 1：原生 function calling（tool_calls 字段，content 作为思考过程）
    - 路径 2：文本 JSON 兜底——```json 代码块优先 + 花括号配平扫描裸 JSON；字段别名
      （name/tool/tool_name/function；arguments/parameters/args/params；thought/thinking/reasoning；answer/final_answer 等）
      支持对象与数组两种形态；兜底生成的调用 id 前缀 `call_fallback_`
    - 思考过程抽取：JSON thought 字段、`<thought>` 标签、`Thought:` / `思考：` 行标签、JSON 外散文
    - 降级：畸形 JSON / 空内容 / 语义不可识别 JSON 一律降级为普通文本最终答案并记日志，不中断流程
  - `tests/test_messages.py`（13）、`tests/test_llm_client.py`（12，含参数化瞬时错误）、`tests/test_parser.py`（22）：共新增 52 个单测
- 设计决策与边界说明：
  - Step 1 已有模块**只使用未修改**；`agent/core/__init__.py`、`agent/llm/__init__.py` 两个 Step 1 占位
    `__init__.py` 也保持原样，统一以完整模块路径导入（`agent.core.messages` / `agent.llm.client` / `agent.llm.parser`）
  - 本机 SDK 为 openai 3.13.0（vendored httpx，无独立 httpx 包），客户端对异常类做存在性过滤以兼容版本差异
- 测试与验证结果：`pytest` **78 passed**（Step 1 的 26 个用例零回归 + 本轮新增 52）；
  `python -m agent` 空壳仍正常退出；真实 API 冒烟因本机无 `.env` 未执行（验收标准中为可选项）
- commit hash：见本轮提交
- 遗留问题：
  - 真实 deepseek/OpenAI 联调（tools 参数、原生 tool_calls 响应）待配置 `.env` 后在 Step 6 端到端阶段验证
  - 文本 JSON 兜底的字段别名只覆盖常见写法；若后续模型出现新格式再增量扩展（只扩展不改契约）
  - 思考过程目前仅在消息模型中透传，是否 / 如何塞入 context 留待 Step 5 按上下文策略决定
