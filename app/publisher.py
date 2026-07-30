"""Publishes a summarized video to the destination website.

The website's real API contract isn't known yet -- build_payload() below
is a best-guess placeholder and is THE function to edit once the real
endpoint/field names/auth scheme are confirmed. Everything else in this
module (the POST mechanics, error handling) should stay the same
regardless of the payload shape.
"""
from __future__ import annotations

import requests

from app.youtube import VideoMetadata


class PublishError(RuntimeError):
    """Raised when the website API request fails: network error or any
    non-2xx response."""


def build_payload(video: VideoMetadata, summary: str) -> dict:
    """Best-guess payload shape. Adjust field names/nesting to match the
    real website API once its contract is known."""
    return {
        "video_id": video.video_id,
        "title": video.title,
        "url": video.watch_url,
        "embed_url": video.embed_url,
        "channel_title": video.channel_title,
        "thumbnail_url": video.thumbnail_url,
        "published_at": video.published_at,
        "summary": summary,
    }


def publish_video(
    api_url: str,
    api_key: str,
    video: VideoMetadata,
    summary: str,
    *,
    session: requests.Session | None = None,
    timeout: int = 30,
) -> requests.Response:
    http = session if session is not None else requests
    try:
        response = http.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=build_payload(video, summary),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise PublishError(
            f"Publishing video {video.video_id} to {api_url} failed: {exc}"
        ) from exc

    if not response.ok:
        raise PublishError(
            f"Publishing video {video.video_id} to {api_url} failed with status "
            f"{response.status_code}: {response.text[:500]}"
        )

    return response
