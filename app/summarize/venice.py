"""Venice AI-backed summary provider.

Venice's chat completions endpoint does technically support a video_url
input type, but YouTube-link support there is model/provider-dependent and
not reliably guaranteed (it's really meant for direct mp4/webm/mov file
URLs). So this fetches a real transcript first (via transcript.py) and
sends it as plain text in an otherwise ordinary, OpenAI-compatible chat
completion request.
"""
from __future__ import annotations

import requests

from app.summarize.base import SummaryError, SummaryProvider
from app.summarize.transcript import TranscriptError, get_transcript
from app.youtube import VideoMetadata

VENICE_CHAT_COMPLETIONS_URL = "https://api.venice.ai/api/v1/chat/completions"

DEFAULT_PROMPT_TEMPLATE = (
    'Below is the transcript of a YouTube video titled "{title}". Write a '
    "concise summary (3-5 sentences) of what it covers, suitable for "
    "posting in plain text alongside the embedded video on a website. "
    "Write the summary in English regardless of the transcript's language. "
    "Do not include a title or preamble -- just the summary text.\n\n"
    "Transcript:\n{transcript}"
)

# Cheap guard against a multi-hour video's transcript overflowing the
# target model's context window.
DEFAULT_MAX_TRANSCRIPT_CHARS = 100_000


class VeniceProvider(SummaryProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        proxy_username: str | None = None,
        proxy_password: str | None = None,
        prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
        max_transcript_chars: int = DEFAULT_MAX_TRANSCRIPT_CHARS,
        session: requests.Session | None = None,
        timeout: int = 60,
    ):
        self._api_key = api_key
        self._model = model
        self._proxy_username = proxy_username
        self._proxy_password = proxy_password
        self._prompt_template = prompt_template
        self._max_transcript_chars = max_transcript_chars
        self._http = session if session is not None else requests
        self._timeout = timeout

    def summarize(self, video: VideoMetadata) -> str:
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
        prompt = self._prompt_template.format(title=video.title, transcript=transcript)

        try:
            response = self._http.post(
                VENICE_CHAT_COMPLETIONS_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise SummaryError(
                f"Venice request failed for video {video.video_id}: {exc}"
            ) from exc

        if response.status_code != 200:
            raise SummaryError(
                f"Venice request failed for video {video.video_id} with status "
                f"{response.status_code}: {response.text[:500]}"
            )

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise SummaryError(
                f"Unexpected Venice response shape for video {video.video_id}: {exc}"
            ) from exc

        text = (content or "").strip()
        if not text:
            raise SummaryError(f"Venice returned an empty summary for video {video.video_id}")
        return text
