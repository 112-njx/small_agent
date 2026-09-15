# 系统 Bug 修复报告

> 用途：记录开发过程中发现的系统 bug 及其修复，由开发 Agent 在修复后**追加**记录。

## 记录格式
- 日期 / 现象 / 复现路径 / 根因 / 修复方案 / 验证结果

---

## 已记录 Bug

（截至 2026-09-15：累计记录 2 个 bug，均已修复并回归验证。）

### Bug 1（2026-09-11）· `.env.example` 被 Git 忽略，模板无法提交
- 现象：新建的 `.env.example` 在 `git add -A` 后不进入暂存区，模板文件无法随仓库交付。
- 复现路径：`git add -A` 后 `git status` 中看不到 `.env.example`。
- 根因：`.gitignore` 中的 `*.env.*` 通配规则同时匹配了 `.env.example`（此前该规则只为忽略本地 `.env` 及变体而设，未考虑模板文件）。
- 修复方案：在 `.gitignore` 的 env 段追加白名单例外 `!.env.example`。
- 验证结果：`git add -A` 后 `.env.example` 被 Git 跟踪（见本轮提交内容）。

### Bug 2（2026-09-15）· 文本 JSON 兜底时同一对象内 thought 字段被漏抽
- 现象：模型输出 ```json 代码块中同时给出 `thought` 与 `name`（如
  `{"thought": "内部思考", "name": "search", "arguments": {...}}`）时，
  解析结果的思考过程错误地变成 JSON 外的散文，而非显式的 thought 字段。
- 复现路径：单测 `test_fenced_json_with_explicit_thought_field`：
  `Parser().parse_text(text).thought` 得到 `"外围散文"`，预期 `"内部思考"`。
- 根因：`parse_text` 遍历 JSON 条目时先取 `name`，命中后立即 `continue`，
  导致同一对象上的 `thought` 字段抽取分支永远不执行。
- 修复方案：调整条目遍历顺序——先抽取 thought 字段（与 json_thought 合并），
  再判断 name 并构造工具调用；无 name 的条目才继续找 answer 字段。
- 验证结果：新增对应单测，修复后 `pytest` 78 passed 全绿。
