"""Gemini-backed summary provider.

Passes the video's YouTube URL directly to the Gemini API, which fetches
and understands the video (video+audio) server-side -- no transcript
fetch involved. Requires the video to be public. See
https://ai.google.dev/gemini-api/docs/video-understanding.
"""
from __future__ import annotations

from google import genai
from google.genai import types

from app.summarize.base import DEFAULT_PROMPT, SummaryError, SummaryProvider
from app.youtube import VideoMetadata

DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiProvider(SummaryProvider):
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, prompt: str = DEFAULT_PROMPT):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._prompt = prompt

    def summarize(self, video: VideoMetadata) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=[
                    self._prompt,
                    types.Part(file_data=types.FileData(file_uri=video.watch_url)),
                ],
            )
        except Exception as exc:
            raise SummaryError(
                f"Gemini request failed for video {video.video_id}: {exc}"
            ) from exc

        text = (response.text or "").strip()
        if not text:
            raise SummaryError(f"Gemini returned an empty summary for video {video.video_id}")
        return text
