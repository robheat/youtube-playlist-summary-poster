"""Fetches a YouTube video's transcript as plain text.

Used by both summary providers (see app/summarize/gemini.py's docstring
for why Gemini also went this route rather than native video ingestion).

Known risk: YouTube aggressively blocks requests from known cloud/CI IP
ranges, including GitHub Actions runners, sometimes on the very first
request. If WEBSHARE_PROXY_USERNAME/PASSWORD are configured, requests are
routed through a Webshare rotating-residential proxy to work around this;
see README.md "Transcript IP blocking".
"""
from __future__ import annotations

from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    YouTubeTranscriptApi,
)
from youtube_transcript_api.proxies import WebshareProxyConfig

# Tried in order; falls back to whatever transcript IS available if none
# of these exist, since the LLM prompt separately instructs "summarize in
# English" regardless of the transcript's source language.
PREFERRED_LANGUAGES = ["en", "en-US", "en-GB"]


class TranscriptError(RuntimeError):
    """Raised when no transcript could be retrieved for a video, whether
    because captions are unavailable/disabled or because the request was
    blocked by YouTube."""


def get_transcript(
    video_id: str,
    *,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
) -> str:
    proxy_config = None
    if proxy_username and proxy_password:
        proxy_config = WebshareProxyConfig(
            proxy_username=proxy_username, proxy_password=proxy_password
        )

    api = YouTubeTranscriptApi(proxy_config=proxy_config)

    try:
        transcript_list = api.list(video_id)
        try:
            transcript = transcript_list.find_transcript(PREFERRED_LANGUAGES)
        except NoTranscriptFound:
            transcript = next(iter(transcript_list))
        fetched = transcript.fetch()
    except CouldNotRetrieveTranscript as exc:
        # CouldNotRetrieveTranscript is the library's common base class for
        # every retrieval failure (disabled captions, blocked IP, video
        # unavailable, ...). Preserving the concrete exception's class name
        # keeps "no captions exist" distinguishable from "we got IP-blocked"
        # in logs, without this module needing to enumerate every subclass.
        raise TranscriptError(
            f"Could not retrieve transcript for video {video_id} "
            f"({type(exc).__name__}): {exc}"
        ) from exc
    except StopIteration as exc:
        raise TranscriptError(f"No transcripts available at all for video {video_id}") from exc

    return " ".join(snippet.text for snippet in fetched).strip()
