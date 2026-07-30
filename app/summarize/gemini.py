"""Gemini-backed article generation.

Passes the video's YouTube URL directly to the Gemini API, which fetches
and understands the video (video+audio) server-side -- no transcript
fetch involved. Requires the video to be public. See
https://ai.google.dev/gemini-api/docs/video-understanding.
"""
from __future__ import annotations

from google import genai
from google.genai import types

from app.config import SiteProfile
from app.summarize.article_json import build_json_instructions, parse_article
from app.summarize.base import ArticleContent, SummaryError, SummaryProvider
from app.youtube import VideoMetadata

DEFAULT_MODEL = "gemini-2.5-flash"

PROMPT_PREFIX = (
    "Watch this YouTube video and write a news-style article about it, "
    "suitable for publishing on a content site alongside the embedded video."
)


class GeminiProvider(SummaryProvider):
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def generate_article(self, video: VideoMetadata, site_profile: SiteProfile) -> ArticleContent:
        prompt = f"{PROMPT_PREFIX}\n\n{build_json_instructions(site_profile)}"

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=[
                    prompt,
                    types.Part(file_data=types.FileData(file_uri=video.watch_url)),
                ],
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
        except Exception as exc:
            raise SummaryError(
                f"Gemini request failed for video {video.video_id}: {exc}"
            ) from exc

        text = (response.text or "").strip()
        if not text:
            raise SummaryError(f"Gemini returned an empty response for video {video.video_id}")

        return parse_article(text, site_profile, video.video_id)
