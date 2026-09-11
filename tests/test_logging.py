"""统一日志单元测试：文件写入、handler 组合、幂等、工具 trace 预留 logger。

每个用例前重置 `agent` 根 logger 的 handler，避免测试间相互污染，
日志文件一律写入 pytest 的 tmp_path。
"""

from __future__ import annotations

import logging

import pytest

import agent.logging as logging_mod
from agent.errors import ConfigError
from agent.logging import (
    ROOT_LOGGER_NAME,
    SESSION_LOGGER_NAME,
    TOOL_TRACE_LOGGER_NAME,
    get_logger,
    get_tool_trace_logger,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    """每个用例开始前清空 agent 根 logger，结束后恢复原状。"""
    root = logging.getLogger(ROOT_LOGGER_NAME)
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers.clear()
    logging_mod._configured = False
    yield
    root.handlers.clear()
    root.setLevel(saved_level)
    for handler in saved_handlers:
        root.addHandler(handler)
    logging_mod._configured = bool(saved_handlers)


def _flush_all(logger_name: str = ROOT_LOGGER_NAME) -> None:
    for handler in logging.getLogger(logger_name).handlers:
        handler.flush()


def test_setup_writes_log_file(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    setup_logging("DEBUG", log_dir=log_dir)

    logging.getLogger(ROOT_LOGGER_NAME).info("hello from test")
    _flush_all()

    log_file = log_dir / "agent.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "hello from test" in content


def test_console_and_file_handlers(tmp_path) -> None:
    setup_logging("INFO", log_dir=tmp_path / "logs")

    root = logging.getLogger(ROOT_LOGGER_NAME)
    handler_types = {type(h).__name__ for h in root.handlers}

    assert "StreamHandler" in handler_types
    assert "RotatingFileHandler" in handler_types


def test_setup_creates_log_dir(tmp_path) -> None:
    log_dir = tmp_path / "a" / "b" / "logs"
    setup_logging("INFO", log_dir=log_dir)

    assert log_dir.is_dir()


def test_setup_logging_idempotent(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    setup_logging("INFO", log_dir=log_dir)
    handler_count = len(logging.getLogger(ROOT_LOGGER_NAME).handlers)

    setup_logging("INFO", log_dir=log_dir)  # 第二次调用不叠加

    assert len(logging.getLogger(ROOT_LOGGER_NAME).handlers) == handler_count


def test_tool_trace_logger_writes_to_file(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    setup_logging("INFO", log_dir=log_dir)

    trace = get_tool_trace_logger()
    assert trace.name == TOOL_TRACE_LOGGER_NAME
    trace.info("tool=calculator args={'a': 1} cost=0.01s")
    _flush_all()

    content = (log_dir / "agent.log").read_text(encoding="utf-8")
    assert "agent.tools" in content
    assert "tool=calculator" in content


def test_session_logger_name_reserved() -> None:
    assert SESSION_LOGGER_NAME == "agent.session"


def test_invalid_level_raises(tmp_path) -> None:
    with pytest.raises(ConfigError):
        setup_logging("VERBOSE", log_dir=tmp_path / "logs")


def test_get_logger_namespace() -> None:
    assert get_logger("tools").name == "agent.tools"
    assert get_logger("agent.tools").name == "agent.tools"
    assert get_logger("core").name == "agent.core"


def test_configure_from_settings(tmp_path, monkeypatch) -> None:
    from agent.config import load_config

    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("AGENT_LOG_DIR", str(tmp_path / "logs"))
    settings = load_config(env_file=None)

    root = logging_mod.configure_from_settings(settings)

    assert root is logging.getLogger(ROOT_LOGGER_NAME)
    logging.getLogger(ROOT_LOGGER_NAME).warning("warning msg")
    _flush_all()
    content = (tmp_path / "logs" / "agent.log").read_text(encoding="utf-8")
    assert "warning msg" in content
