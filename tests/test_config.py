"""Tests for app.config.load_config's validation rules."""
from __future__ import annotations

import pytest

from app import config as config_module
from app.config import ConfigError, load_config

REQUIRED_GEMINI_ENV = {
    "YOUTUBE_API_KEY": "yt-key",
    "PLAYLIST_ID": "PL123",
    "SUMMARY_PROVIDER": "gemini",
    "GEMINI_API_KEY": "gemini-key",
    "WEBSITE_API_URL": "https://example.com/api/videos",
    "WEBSITE_API_KEY": "website-key",
}

REQUIRED_VENICE_ENV = {
    "YOUTUBE_API_KEY": "yt-key",
    "PLAYLIST_ID": "PL123",
    "SUMMARY_PROVIDER": "venice",
    "VENICE_API_KEY": "venice-key",
    "VENICE_MODEL": "some-venice-model",
    "WEBSITE_API_URL": "https://example.com/api/videos",
    "WEBSITE_API_KEY": "website-key",
}

ALL_KNOWN_VARS = [
    "YOUTUBE_API_KEY",
    "PLAYLIST_ID",
    "SUMMARY_PROVIDER",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "VENICE_API_KEY",
    "VENICE_MODEL",
    "WEBSHARE_PROXY_USERNAME",
    "WEBSHARE_PROXY_PASSWORD",
    "WEBSITE_API_URL",
    "WEBSITE_API_KEY",
    "MAX_VIDEOS_PER_RUN",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ALL_KNOWN_VARS:
        monkeypatch.delenv(name, raising=False)
    # Keep tests hermetic regardless of any real .env file on disk.
    monkeypatch.setattr(config_module, "load_dotenv", lambda *a, **k: False)


def _set_env(monkeypatch, overrides: dict) -> None:
    for key, value in overrides.items():
        monkeypatch.setenv(key, value)


def test_valid_gemini_config_succeeds(monkeypatch):
    _set_env(monkeypatch, REQUIRED_GEMINI_ENV)
    cfg = load_config()
    assert cfg.summary_provider == "gemini"
    assert cfg.gemini_model == "gemini-2.5-flash"
    assert cfg.max_videos_per_run == 5


def test_valid_venice_config_succeeds(monkeypatch):
    _set_env(monkeypatch, REQUIRED_VENICE_ENV)
    cfg = load_config()
    assert cfg.summary_provider == "venice"
    assert cfg.venice_model == "some-venice-model"


def test_summary_provider_is_case_insensitive(monkeypatch):
    _set_env(monkeypatch, {**REQUIRED_GEMINI_ENV, "SUMMARY_PROVIDER": "GEMINI"})
    cfg = load_config()
    assert cfg.summary_provider == "gemini"


@pytest.mark.parametrize("missing", ["YOUTUBE_API_KEY", "PLAYLIST_ID", "SUMMARY_PROVIDER"])
def test_missing_always_required_var_fails(monkeypatch, missing):
    env = dict(REQUIRED_GEMINI_ENV)
    del env[missing]
    _set_env(monkeypatch, env)
    with pytest.raises(ConfigError, match=missing):
        load_config()


def test_invalid_summary_provider_fails(monkeypatch):
    _set_env(monkeypatch, {**REQUIRED_GEMINI_ENV, "SUMMARY_PROVIDER": "chatgpt"})
    with pytest.raises(ConfigError, match="SUMMARY_PROVIDER"):
        load_config()


def test_gemini_provider_without_gemini_key_fails(monkeypatch):
    env = dict(REQUIRED_GEMINI_ENV)
    del env["GEMINI_API_KEY"]
    _set_env(monkeypatch, env)
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        load_config()


def test_venice_provider_without_venice_key_fails(monkeypatch):
    env = dict(REQUIRED_VENICE_ENV)
    del env["VENICE_API_KEY"]
    _set_env(monkeypatch, env)
    with pytest.raises(ConfigError, match="VENICE_API_KEY"):
        load_config()


def test_venice_provider_without_venice_model_fails(monkeypatch):
    env = dict(REQUIRED_VENICE_ENV)
    del env["VENICE_MODEL"]
    _set_env(monkeypatch, env)
    with pytest.raises(ConfigError, match="VENICE_MODEL"):
        load_config()


def test_venice_config_does_not_require_gemini_key(monkeypatch):
    _set_env(monkeypatch, REQUIRED_VENICE_ENV)
    cfg = load_config()
    assert cfg.gemini_api_key is None


def test_proxy_username_without_password_fails(monkeypatch):
    _set_env(monkeypatch, {**REQUIRED_GEMINI_ENV, "WEBSHARE_PROXY_USERNAME": "user"})
    with pytest.raises(ConfigError, match="WEBSHARE_PROXY"):
        load_config()


def test_proxy_password_without_username_fails(monkeypatch):
    _set_env(monkeypatch, {**REQUIRED_GEMINI_ENV, "WEBSHARE_PROXY_PASSWORD": "pass"})
    with pytest.raises(ConfigError, match="WEBSHARE_PROXY"):
        load_config()


def test_proxy_both_set_succeeds(monkeypatch):
    _set_env(
        monkeypatch,
        {
            **REQUIRED_GEMINI_ENV,
            "WEBSHARE_PROXY_USERNAME": "user",
            "WEBSHARE_PROXY_PASSWORD": "pass",
        },
    )
    cfg = load_config()
    assert cfg.webshare_proxy_username == "user"
    assert cfg.webshare_proxy_password == "pass"


def test_website_vars_not_required_in_dry_run(monkeypatch):
    env = dict(REQUIRED_GEMINI_ENV)
    del env["WEBSITE_API_URL"]
    del env["WEBSITE_API_KEY"]
    _set_env(monkeypatch, env)
    cfg = load_config(dry_run=True)
    assert cfg.website_api_url is None
    assert cfg.website_api_key is None


def test_website_vars_required_outside_dry_run(monkeypatch):
    env = dict(REQUIRED_GEMINI_ENV)
    del env["WEBSITE_API_URL"]
    _set_env(monkeypatch, env)
    with pytest.raises(ConfigError, match="WEBSITE_API_URL"):
        load_config(dry_run=False)


@pytest.mark.parametrize("raw_value", ["not-a-number", "0", "-3"])
def test_invalid_max_videos_per_run_fails(monkeypatch, raw_value):
    _set_env(monkeypatch, {**REQUIRED_GEMINI_ENV, "MAX_VIDEOS_PER_RUN": raw_value})
    with pytest.raises(ConfigError, match="MAX_VIDEOS_PER_RUN"):
        load_config()


def test_valid_max_videos_per_run_is_parsed(monkeypatch):
    _set_env(monkeypatch, {**REQUIRED_GEMINI_ENV, "MAX_VIDEOS_PER_RUN": "10"})
    cfg = load_config()
    assert cfg.max_videos_per_run == 10


def test_empty_string_env_var_treated_as_unset(monkeypatch):
    # Simulates an unset GitHub Actions Variable, which interpolates as ""
    _set_env(monkeypatch, {**REQUIRED_GEMINI_ENV, "GEMINI_MODEL": ""})
    cfg = load_config()
    assert cfg.gemini_model == "gemini-2.5-flash"


def test_reports_all_errors_at_once(monkeypatch):
    with pytest.raises(ConfigError) as exc_info:
        load_config()
    message = str(exc_info.value)
    assert "YOUTUBE_API_KEY" in message
    assert "PLAYLIST_ID" in message
    assert "SUMMARY_PROVIDER" in message
