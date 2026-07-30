"""Common interface implemented by every article-generation provider."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import SiteProfile
from app.youtube import VideoMetadata


class SummaryError(RuntimeError):
    """Raised for any failure while generating an article: network errors,
    auth failures, quota limits, an unavailable/missing transcript, or a
    response that fails validation (see app/summarize/article_json.py).

    main.py additionally wraps each video's processing in a broad
    `except Exception` as a defense-in-depth backstop, but providers should
    raise this for every failure mode they can anticipate so failures are
    identifiable in logs.
    """


@dataclass(frozen=True)
class ArticleContent:
    title: str
    summary: str
    body: str
    category: str
    tags: list[str]


class SummaryProvider(ABC):
    @abstractmethod
    def generate_article(self, video: VideoMetadata, site_profile: SiteProfile) -> ArticleContent:
        """Returns a structured article for the video, written to match
        site_profile's category taxonomy and body style. Raises
        SummaryError on failure."""
        raise NotImplementedError
