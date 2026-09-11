# 系统 Bug 修复报告

> 用途：记录开发过程中发现的系统 bug 及其修复，由开发 Agent 在修复后**追加**记录。

## 记录格式
- 日期 / 现象 / 复现路径 / 根因 / 修复方案 / 验证结果

---

## 已记录 Bug

（截至 2026-09-11：暂无 bug 记录，第一轮开发尚未开始。）

### Bug 1（2026-09-11）· `.env.example` 被 Git 忽略，模板无法提交
- 现象：新建的 `.env.example` 在 `git add -A` 后不进入暂存区，模板文件无法随仓库交付。
- 复现路径：`git add -A` 后 `git status` 中看不到 `.env.example`。
- 根因：`.gitignore` 中的 `*.env.*` 通配规则同时匹配了 `.env.example`（此前该规则只为忽略本地 `.env` 及变体而设，未考虑模板文件）。
- 修复方案：在 `.gitignore` 的 env 段追加白名单例外 `!.env.example`。
- 验证结果：`git add -A` 后 `.env.example` 被 Git 跟踪（见本轮提交内容）。
