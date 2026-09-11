"""配置加载单元测试。

要点：覆盖完整加载、默认值、缺 key 报错、回退项、非法取值、.env 文件与
真实环境变量的优先级关系。所有用例通过 monkeypatch 隔离环境变量，
不影响真实系统环境。
"""

from __future__ import annotations

import pytest

from agent.config import (
    DEFAULT_BASE_URL,
    DEFAULT_CONTEXT_THRESHOLD,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_ROUNDS,
    DEFAULT_MODEL,
    load_config,
)
from agent.errors import ConfigError

_ALL_ENV_KEYS = (
    "LLM_API_KEY",
    "OPENAI_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "AGENT_MAX_ROUNDS",
    "AGENT_CONTEXT_THRESHOLD",
    "LOG_LEVEL",
    "AGENT_LOG_DIR",
)


def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ALL_ENV_KEYS:
        monkeypatch.delenv(name, raising=False)


def test_full_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "sk-test-123")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-test")
    monkeypatch.setenv("AGENT_MAX_ROUNDS", "5")
    monkeypatch.setenv("AGENT_CONTEXT_THRESHOLD", "4096")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("AGENT_LOG_DIR", "logs_test")

    settings = load_config(env_file=None)

    assert settings.api_key == "sk-test-123"
    assert settings.base_url == "https://example.com/v1"
    assert settings.model == "gpt-test"
    assert settings.max_rounds == 5
    assert settings.context_threshold == 4096
    assert settings.log_level == "DEBUG"  # 归一化为大写
    assert settings.log_dir == "logs_test"


def test_defaults_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "sk-test")

    settings = load_config(env_file=None)

    assert settings.base_url == DEFAULT_BASE_URL
    assert settings.model == DEFAULT_MODEL
    assert settings.max_rounds == DEFAULT_MAX_ROUNDS
    assert settings.context_threshold == DEFAULT_CONTEXT_THRESHOLD
    assert settings.log_level == DEFAULT_LOG_LEVEL
    assert settings.log_dir == "logs"


def test_missing_api_key_raises_readable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)

    with pytest.raises(ConfigError) as exc_info:
        load_config(env_file=None)

    message = str(exc_info.value)
    assert "LLM_API_KEY" in message
    assert ".env" in message  # 给出修复指引


def test_api_key_fallback_to_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fallback")

    settings = load_config(env_file=None)

    assert settings.api_key == "sk-fallback"


def test_blank_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "   ")

    with pytest.raises(ConfigError):
        load_config(env_file=None)


def test_invalid_int_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_MAX_ROUNDS", "abc")

    with pytest.raises(ConfigError) as exc_info:
        load_config(env_file=None)

    assert "AGENT_MAX_ROUNDS" in str(exc_info.value)


def test_non_positive_int_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_MAX_ROUNDS", "0")
    with pytest.raises(ConfigError):
        load_config(env_file=None)

    monkeypatch.setenv("AGENT_MAX_ROUNDS", "-3")
    with pytest.raises(ConfigError):
        load_config(env_file=None)


def test_invalid_log_level_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")

    with pytest.raises(ConfigError) as exc_info:
        load_config(env_file=None)

    assert "LOG_LEVEL" in str(exc_info.value)


def test_dotenv_file_loading(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_API_KEY=sk-from-file\nLLM_MODEL=gpt-file\nAGENT_MAX_ROUNDS=3\n",
        encoding="utf-8",
    )

    settings = load_config(env_file=env_file)

    assert settings.api_key == "sk-from-file"
    assert settings.model == "gpt-file"
    assert settings.max_rounds == 3


def test_env_var_overrides_dotenv(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_API_KEY=sk-from-file\nLLM_MODEL=gpt-file\n", encoding="utf-8"
    )
    monkeypatch.setenv("LLM_MODEL", "gpt-env")

    settings = load_config(env_file=env_file)

    assert settings.api_key == "sk-from-file"  # 文件负责补缺
    assert settings.model == "gpt-env"  # 真实环境变量优先


def test_required_false_returns_empty_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_keys(monkeypatch)

    settings = load_config(env_file=None, required=False)

    assert settings.api_key == ""
    assert settings.model == DEFAULT_MODEL
