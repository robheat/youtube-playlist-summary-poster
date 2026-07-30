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

        # No response_mime_type="application/json" config here -- the JSON
        # instruction in the prompt plus article_json.extract_json()'s
        # fence/commentary stripping does the same job without it, and it
        # wasn't the cause of the 400 below anyway (removing it alone
        # didn't fix it).
        #
        # mime_type is required despite the docs describing YouTube URLs as
        # needing "no explicit mime_type": FileData.mime_type is documented
        # "Required" in the SDK, and Part.from_uri() -- the SDK's own
        # helper -- raises ValueError trying to mimetypes.guess_type() a
        # bare watch?v= URL with no file extension. Confirmed via live
        # testing that omitting it produces a generic 400 INVALID_ARGUMENT
        # regardless of model (tried gemini-3.5-flash and gemini-3.6-flash).
        # The actual value isn't validated against real content -- YouTube
        # URLs get special-cased server-side -- so a generic video mime
        # type satisfies the required field.
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=[
                    prompt,
                    types.Part(
                        file_data=types.FileData(
                            file_uri=video.watch_url, mime_type="video/mp4"
                        )
                    ),
                ],
            )
        except Exception as exc:
            raise SummaryError(
                f"Gemini request failed for video {video.video_id}: {exc}"
            ) from exc

        text = (response.text or "").strip()
        if not text:
            raise SummaryError(f"Gemini returned an empty response for video {video.video_id}")

        return parse_article(text, site_profile, video.video_id)
