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
DEFAULT_VENICE_MODEL = "mistral-small-3-2-24b-instruct"
DEFAULT_MAX_VIDEOS_PER_RUN = 5

VALID_PROVIDERS = {"gemini", "venice"}


@dataclass(frozen=True)
class SiteProfile:
    key: str
    repo_owner: str
    repo_name: str
    default_branch: str
    playlist_id: str
    categories: tuple[str, ...]
    default_source_name: str
    body_style_hint: str = (
        "2-4 plain-prose paragraphs separated by a blank line. You may "
        "start a paragraph with '## ' or '### ' for a subheading where it "
        "genuinely helps (optional)."
    )


# Playlist IDs and category taxonomies live here, not in env vars -- this
# removes any chance of mismatching a playlist to the wrong site via a
# YAML typo, and keeps each site's fixed category enum in one place.
SITE_PROFILES: dict[str, SiteProfile] = {
    "cryptocatalyst-news": SiteProfile(
        key="cryptocatalyst-news",
        repo_owner="robheat",
        repo_name="cryptocatalyst-news",
        default_branch="master",
        playlist_id="PLLuz1PRurl7k",
        categories=("bitcoin", "ethereum", "defi", "nft", "policy", "web3", "general"),
        default_source_name="YouTube",
    ),
    "ainformed-dev": SiteProfile(
        key="ainformed-dev",
        repo_owner="robheat",
        repo_name="ainformed-dev",
        default_branch="master",
        playlist_id="PLTVCsU2gFTts",
        categories=("models", "research", "tools", "policy", "industry", "open-source", "general"),
        default_source_name="YouTube",
    ),
}


class ConfigError(RuntimeError):
    """Raised with EVERY configuration problem found, not just the first --
    important for an unattended scheduled job where fixing one missing
    secret per failed run would be painful."""


@dataclass(frozen=True)
class Config:
    youtube_api_key: str
    target_site: str
    site_profile: SiteProfile
    summary_provider: str
    gemini_api_key: str | None
    gemini_model: str
    venice_api_key: str | None
    venice_model: str
    webshare_proxy_username: str | None
    webshare_proxy_password: str | None
    site_repo_pat: str | None
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

    target_site = _get("TARGET_SITE")
    site_profile: SiteProfile | None = None
    if not target_site:
        errors.append(
            f"TARGET_SITE is required (must be one of: {', '.join(sorted(SITE_PROFILES))})."
        )
    elif target_site not in SITE_PROFILES:
        errors.append(
            f"TARGET_SITE={target_site!r} is invalid; must be one of: "
            f"{', '.join(sorted(SITE_PROFILES))}."
        )
    else:
        site_profile = SITE_PROFILES[target_site]

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

    venice_api_key = _get("VENICE_AI_API_KEY")
    if summary_provider == "venice" and not venice_api_key:
        errors.append("VENICE_AI_API_KEY is required because SUMMARY_PROVIDER=venice.")
    venice_model = _get("VENICE_MODEL") or DEFAULT_VENICE_MODEL

    webshare_proxy_username = _get("WEBSHARE_PROXY_USERNAME")
    webshare_proxy_password = _get("WEBSHARE_PROXY_PASSWORD")
    if bool(webshare_proxy_username) != bool(webshare_proxy_password):
        errors.append(
            "WEBSHARE_PROXY_USERNAME and WEBSHARE_PROXY_PASSWORD must both be set, "
            "or both left unset."
        )

    site_repo_pat = _get("SITE_REPO_PAT")
    if not dry_run and not site_repo_pat:
        errors.append("SITE_REPO_PAT is required (unless running with --dry-run).")

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
        target_site=target_site,
        site_profile=site_profile,
        summary_provider=summary_provider,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        venice_api_key=venice_api_key,
        venice_model=venice_model,
        webshare_proxy_username=webshare_proxy_username,
        webshare_proxy_password=webshare_proxy_password,
        site_repo_pat=site_repo_pat,
        max_videos_per_run=max_videos_per_run,
        state_file_path=f"data/processed_videos_{target_site}.json",
    )
