"""Pluggable video summarization providers.

Two backends are available, selected via the SUMMARY_PROVIDER config value:

- gemini: passes the YouTube URL directly to the Gemini API, which fetches
  and understands the video itself. No transcript fetch involved.
- venice: fetches a transcript via youtube-transcript-api and sends it as
  plain text to Venice's chat completions endpoint. Venice's own video_url
  input type exists but YouTube-link support is inconsistent across
  models, so it is not relied on here.
"""
from __future__ import annotations

from app.config import Config
from app.summarize.base import SummaryError, SummaryProvider
from app.summarize.gemini import GeminiProvider
from app.summarize.venice import VeniceProvider

__all__ = ["SummaryError", "SummaryProvider", "get_provider"]


def get_provider(config: Config) -> SummaryProvider:
    """Factory dispatching on config.summary_provider. Assumes config has
    already been validated by config.load_config() -- no error handling
    for missing keys happens here.
    """
    if config.summary_provider == "gemini":
        return GeminiProvider(api_key=config.gemini_api_key, model=config.gemini_model)
    if config.summary_provider == "venice":
        return VeniceProvider(
            api_key=config.venice_api_key,
            model=config.venice_model,
            proxy_username=config.webshare_proxy_username,
            proxy_password=config.webshare_proxy_password,
        )
    raise ValueError(f"Unknown summary provider: {config.summary_provider!r}")
