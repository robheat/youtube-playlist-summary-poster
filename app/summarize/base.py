"""Common interface implemented by every summary provider."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.youtube import VideoMetadata

DEFAULT_PROMPT = (
    "Watch this YouTube video and write a concise summary (3-5 sentences) "
    "of what it covers, suitable for posting in plain text alongside the "
    "embedded video on a website. Write the summary in English regardless "
    "of the video's original language. Do not include a title or "
    "preamble -- just the summary text."
)


class SummaryError(RuntimeError):
    """Raised for any failure while generating a summary: network errors,
    auth failures, quota limits, an unavailable/missing transcript, or an
    empty model response.

    main.py additionally wraps each video's processing in a broad
    `except Exception` as a defense-in-depth backstop, but providers should
    raise this for every failure mode they can anticipate so failures are
    identifiable in logs.
    """


class SummaryProvider(ABC):
    @abstractmethod
    def summarize(self, video: VideoMetadata) -> str:
        """Returns a plain-text summary of the video. Raises SummaryError
        on failure."""
        raise NotImplementedError
