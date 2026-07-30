"""Tests for app.config.load_config's validation rules."""
from __future__ import annotations

import pytest

from app import config as config_module
from app.config import SITE_PROFILES, ConfigError, load_config

REQUIRED_GEMINI_ENV = {
    "YOUTUBE_API_KEY": "yt-key",
    "TARGET_SITE": "cryptocatalyst-news",
    "SUMMARY_PROVIDER": "gemini",
    "GEMINI_API_KEY": "gemini-key",
    "SITE_REPO_PAT": "pat-token",
}

REQUIRED_VENICE_ENV = {
    "YOUTUBE_API_KEY": "yt-key",
    "TARGET_SITE": "ainformed-dev",
    "SUMMARY_PROVIDER": "venice",
    "VENICE_AI_API_KEY": "venice-key",
    "SITE_REPO_PAT": "pat-token",
}

ALL_KNOWN_VARS = [
    "YOUTUBE_API_KEY",
    "TARGET_SITE",
    "SUMMARY_PROVIDER",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "VENICE_AI_API_KEY",
    "VENICE_MODEL",
    "WEBSHARE_PROXY_USERNAME",
    "WEBSHARE_PROXY_PASSWORD",
    "SITE_REPO_PAT",
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
    assert cfg.gemini_model == "gemini-3.6-flash"
    assert cfg.max_videos_per_run == 5


def test_valid_venice_config_succeeds(monkeypatch):
    _set_env(monkeypatch, REQUIRED_VENICE_ENV)
    cfg = load_config()
    assert cfg.summary_provider == "venice"
    assert cfg.venice_model == "mistral-small-3-2-24b-instruct"


def test_site_profile_resolved_from_target_site(monkeypatch):
    _set_env(monkeypatch, REQUIRED_GEMINI_ENV)
    cfg = load_config()
    assert cfg.site_profile is SITE_PROFILES["cryptocatalyst-news"]
    assert cfg.site_profile.playlist_id == "PLLuz1PRurl7k"
    assert cfg.state_file_path == "data/processed_videos_cryptocatalyst-news.json"


def test_summary_provider_is_case_insensitive(monkeypatch):
    _set_env(monkeypatch, {**REQUIRED_GEMINI_ENV, "SUMMARY_PROVIDER": "GEMINI"})
    cfg = load_config()
    assert cfg.summary_provider == "gemini"


@pytest.mark.parametrize("missing", ["YOUTUBE_API_KEY", "TARGET_SITE", "SUMMARY_PROVIDER"])
def test_missing_always_required_var_fails(monkeypatch, missing):
    env = dict(REQUIRED_GEMINI_ENV)
    del env[missing]
    _set_env(monkeypatch, env)
    with pytest.raises(ConfigError, match=missing):
        load_config()


def test_invalid_target_site_fails(monkeypatch):
    _set_env(monkeypatch, {**REQUIRED_GEMINI_ENV, "TARGET_SITE": "some-other-site"})
    with pytest.raises(ConfigError, match="TARGET_SITE"):
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
    del env["VENICE_AI_API_KEY"]
    _set_env(monkeypatch, env)
    with pytest.raises(ConfigError, match="VENICE_AI_API_KEY"):
        load_config()


def test_venice_provider_without_venice_model_uses_default(monkeypatch):
    env = dict(REQUIRED_VENICE_ENV)
    _set_env(monkeypatch, env)
    cfg = load_config()
    assert cfg.venice_model == "mistral-small-3-2-24b-instruct"


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


def test_site_repo_pat_not_required_in_dry_run(monkeypatch):
    env = dict(REQUIRED_GEMINI_ENV)
    del env["SITE_REPO_PAT"]
    _set_env(monkeypatch, env)
    cfg = load_config(dry_run=True)
    assert cfg.site_repo_pat is None


def test_site_repo_pat_required_outside_dry_run(monkeypatch):
    env = dict(REQUIRED_GEMINI_ENV)
    del env["SITE_REPO_PAT"]
    _set_env(monkeypatch, env)
    with pytest.raises(ConfigError, match="SITE_REPO_PAT"):
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
    assert cfg.gemini_model == "gemini-3.6-flash"


def test_reports_all_errors_at_once(monkeypatch):
    with pytest.raises(ConfigError) as exc_info:
        load_config()
    message = str(exc_info.value)
    assert "YOUTUBE_API_KEY" in message
    assert "TARGET_SITE" in message
    assert "SUMMARY_PROVIDER" in message
