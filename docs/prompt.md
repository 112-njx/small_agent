# 新 Agent 第一轮开发提示词（Step 1：项目骨架与基础设施）

## 你是谁
你是 small_agent 项目的开发 Agent。项目目标：**从零实现一个最小可用 Agent**——核心 Agent Runtime 必须自行实现，禁止依赖 langgraph / openhands / openclaw / PI 等现成框架。完整需求见项目根目录 `readme.md`。

## 环境
- 项目根目录：`D:\small_agent`（Windows / PowerShell 环境）
- 开发规划：`docs/roadmap.md`（已做拓扑依赖分析；**本轮只做 Step 1**，它是唯一根步骤，无前置依赖）
- Git：已连接 GitHub，`origin = https://github.com/112-njx/small_agent.git`，分支 `main`；完成后直接 commit + push

## 本轮任务：Step 1 项目骨架与基础设施
目标：搭好工程骨架（目录、配置、日志、异常体系），让后续步骤有稳定落点。

1. **目录结构**：按 roadmap.md 建立
   ```
   agent/{core,llm,tools,session}/、tests/、logs/、.env.example、pyproject.toml
   ```
2. **pyproject.toml**：声明依赖（openai SDK、python-dotenv、pytest 等）
3. **agent/config.py**：从 `.env` / 环境变量加载 LLM 配置（api_key、base_url、model、max_rounds、上下文阈值、日志级别），缺失配置给出明确报错
4. **统一日志**：控制台 + 文件（写入 `logs/`），为后续工具 trace 预留独立 logger
5. **异常体系**：`AgentError` 基类 + `ConfigError / LLMError / ToolError / SessionError`

## 验收标准
- `python -m agent` 空壳可启动不报错
- 配置可正常加载，缺 key 时给出可读错误
- 日志能写入 `logs/`；单测覆盖配置加载与异常层级

## 开发约定
- 每个功能点写单元测试，`pytest` 全绿后再提交
- **编码记录**追加到 `docs/code.md`；过程中发现的 bug 及修复写入 `docs/bug.md`（格式见两文件头部说明）
- 完成后提交：`git add -A && git commit -m "feat: step1 project skeleton" && git push`

## 完成后回报
交付物清单、pytest 结果、commit hash、遗留问题。
