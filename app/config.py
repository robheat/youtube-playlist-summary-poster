"""Loads and validates configuration from environment variables.

Calls load_dotenv() so a local .env file (see .env.example) works for
local runs; in GitHub Actions these are set as repo Secrets/Variables
instead, no .env file exists, and load_dotenv() is a safe no-op.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_MAX_VIDEOS_PER_RUN = 5
DEFAULT_STATE_FILE_PATH = "data/processed_videos.json"

VALID_PROVIDERS = {"gemini", "venice"}


class ConfigError(RuntimeError):
    """Raised with EVERY configuration problem found, not just the first --
    important for an unattended scheduled job where fixing one missing
    secret per failed run would be painful."""


@dataclass(frozen=True)
class Config:
    youtube_api_key: str
    playlist_id: str
    summary_provider: str
    gemini_api_key: str | None
    gemini_model: str
    venice_api_key: str | None
    venice_model: str | None
    webshare_proxy_username: str | None
    webshare_proxy_password: str | None
    website_api_url: str | None
    website_api_key: str | None
    max_videos_per_run: int
    state_file_path: str


def _get(name: str) -> str | None:
    # An unset GitHub Actions Variable interpolates as "" in env:, so
    # empty string must be treated the same as "unset" everywhere.
    value = os.environ.get(name)
    return value if value else None


def load_config(*, dry_run: bool = False) -> Config:
    load_dotenv()
    errors: list[str] = []

    youtube_api_key = _get("YOUTUBE_API_KEY")
    if not youtube_api_key:
        errors.append("YOUTUBE_API_KEY is required.")

    playlist_id = _get("PLAYLIST_ID")
    if not playlist_id:
        errors.append("PLAYLIST_ID is required.")

    summary_provider_raw = _get("SUMMARY_PROVIDER")
    summary_provider = summary_provider_raw.lower() if summary_provider_raw else None
    if not summary_provider:
        errors.append("SUMMARY_PROVIDER is required (must be 'gemini' or 'venice').")
    elif summary_provider not in VALID_PROVIDERS:
        errors.append(
            f"SUMMARY_PROVIDER={summary_provider_raw!r} is invalid; must be 'gemini' or 'venice'."
        )

    gemini_api_key = _get("GEMINI_API_KEY")
    if summary_provider == "gemini" and not gemini_api_key:
        errors.append("GEMINI_API_KEY is required because SUMMARY_PROVIDER=gemini.")
    gemini_model = _get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL

    venice_api_key = _get("VENICE_API_KEY")
    venice_model = _get("VENICE_MODEL")
    if summary_provider == "venice":
        if not venice_api_key:
            errors.append("VENICE_API_KEY is required because SUMMARY_PROVIDER=venice.")
        if not venice_model:
            errors.append(
                "VENICE_MODEL is required because SUMMARY_PROVIDER=venice "
                "(there is no safe default -- pick a model from your Venice account)."
            )

    webshare_proxy_username = _get("WEBSHARE_PROXY_USERNAME")
    webshare_proxy_password = _get("WEBSHARE_PROXY_PASSWORD")
    if bool(webshare_proxy_username) != bool(webshare_proxy_password):
        errors.append(
            "WEBSHARE_PROXY_USERNAME and WEBSHARE_PROXY_PASSWORD must both be set, "
            "or both left unset."
        )

    website_api_url = _get("WEBSITE_API_URL")
    website_api_key = _get("WEBSITE_API_KEY")
    if not dry_run:
        if not website_api_url:
            errors.append("WEBSITE_API_URL is required (unless running with --dry-run).")
        if not website_api_key:
            errors.append("WEBSITE_API_KEY is required (unless running with --dry-run).")

    max_videos_raw = _get("MAX_VIDEOS_PER_RUN")
    max_videos_per_run = DEFAULT_MAX_VIDEOS_PER_RUN
    if max_videos_raw is not None:
        try:
            max_videos_per_run = int(max_videos_raw)
            if max_videos_per_run <= 0:
                raise ValueError
        except ValueError:
            errors.append(f"MAX_VIDEOS_PER_RUN={max_videos_raw!r} must be a positive integer.")

    if errors:
        raise ConfigError("Invalid configuration:\n" + "\n".join(f"  - {e}" for e in errors))

    return Config(
        youtube_api_key=youtube_api_key,
        playlist_id=playlist_id,
        summary_provider=summary_provider,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        venice_api_key=venice_api_key,
        venice_model=venice_model,
        webshare_proxy_username=webshare_proxy_username,
        webshare_proxy_password=webshare_proxy_password,
        website_api_url=website_api_url,
        website_api_key=website_api_key,
        max_videos_per_run=max_videos_per_run,
        state_file_path=DEFAULT_STATE_FILE_PATH,
    )
