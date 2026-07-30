"""Pluggable video summarization providers.

Two backends are available, selected via the SUMMARY_PROVIDER config value.
Both fetch a transcript via youtube-transcript-api (transcript.py) and
send it as plain text to their respective LLM -- Gemini's native
YouTube-URL video ingestion was tried and abandoned (see gemini.py's
docstring for why), so there is no meaningful difference between the two
providers beyond which LLM writes the article. Both are therefore subject
to the transcript IP-blocking risk described in transcript.py.

- gemini: sends the transcript to the Gemini API.
- venice: sends the transcript to Venice's chat completions endpoint.
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
        return GeminiProvider(
            api_key=config.gemini_api_key,
            model=config.gemini_model,
            proxy_username=config.webshare_proxy_username,
            proxy_password=config.webshare_proxy_password,
        )
    if config.summary_provider == "venice":
        return VeniceProvider(
            api_key=config.venice_api_key,
            model=config.venice_model,
            proxy_username=config.webshare_proxy_username,
            proxy_password=config.webshare_proxy_password,
        )
    raise ValueError(f"Unknown summary provider: {config.summary_provider!r}")
