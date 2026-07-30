"""Gemini-backed article generation.

Originally passed the video's YouTube URL directly to Gemini for native
video understanding (no transcript fetch). Abandoned after live testing:
gemini-2.5-flash (the model this was verified against during planning) is
no longer available to new API keys, and the current model family
(3.5-flash, 3.6-flash) returns a generic 400 INVALID_ARGUMENT on the video
FileData part that survived ruling out JSON-mode config, a missing
mime_type, and the SDK's content-list grouping (all checked directly
against the installed SDK source). Rather than keep guessing against a
preview feature with an opaque error, this now fetches a transcript (via
transcript.py, the same helper the Venice provider uses) and summarizes
text -- structurally identical to VeniceProvider, just a different LLM
backend. This also means the YouTube transcript IP-blocking risk (see
transcript.py) now applies to the Gemini path too, not just Venice.
"""
from __future__ import annotations

from google import genai

from app.config import SiteProfile
from app.summarize.article_json import build_json_instructions, parse_article
from app.summarize.base import ArticleContent, SummaryError, SummaryProvider
from app.summarize.transcript import TranscriptError, get_transcript
from app.youtube import VideoMetadata

DEFAULT_MODEL = "gemini-2.5-flash"

PROMPT_PREFIX_TEMPLATE = (
    'Below is the transcript of a YouTube video titled "{title}". Write a '
    "news-style article about it, suitable for publishing on a content "
    "site alongside the embedded video."
)

# Cheap guard against a multi-hour video's transcript overflowing the
# target model's context window.
DEFAULT_MAX_TRANSCRIPT_CHARS = 100_000


class GeminiProvider(SummaryProvider):
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        *,
        proxy_username: str | None = None,
        proxy_password: str | None = None,
        max_transcript_chars: int = DEFAULT_MAX_TRANSCRIPT_CHARS,
    ):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._proxy_username = proxy_username
        self._proxy_password = proxy_password
        self._max_transcript_chars = max_transcript_chars

    def generate_article(self, video: VideoMetadata, site_profile: SiteProfile) -> ArticleContent:
        try:
            transcript = get_transcript(
                video.video_id,
                proxy_username=self._proxy_username,
                proxy_password=self._proxy_password,
            )
        except TranscriptError as exc:
            raise SummaryError(str(exc)) from exc

        if not transcript:
            raise SummaryError(f"Empty transcript for video {video.video_id}")

        transcript = transcript[: self._max_transcript_chars]
        prompt = (
            f"{PROMPT_PREFIX_TEMPLATE.format(title=video.title)}\n\n"
            f"{build_json_instructions(site_profile)}\n\n"
            f"Transcript:\n{transcript}"
        )

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=[prompt],
            )
        except Exception as exc:
            raise SummaryError(
                f"Gemini request failed for video {video.video_id}: {exc}"
            ) from exc

        text = (response.text or "").strip()
        if not text:
            raise SummaryError(f"Gemini returned an empty response for video {video.video_id}")

        return parse_article(text, site_profile, video.video_id)
