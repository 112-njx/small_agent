"""`python -m agent` 入口（Step 1 空壳）。

当前仅打印启动横幅并正常退出，验证工程骨架可导入、可运行。
后续 Step 6 将在此接入完整 REPL（多窗口会话 / 工具调用展示等）。

说明：空壳阶段不加载配置——缺 LLM_API_KEY 时启动也不报错；
真实运行（Step 6 起）才调用 `load_config()`，缺失配置会抛出可读的 ConfigError。
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    _ = argv  # 预留参数
    print("small_agent skeleton started (Step 1: project skeleton & infra).")
    print("LLM / tool / session modules will land in Step 2-5; REPL in Step 6.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
