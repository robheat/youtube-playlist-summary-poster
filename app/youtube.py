"""YouTube Data API v3 client for reading a playlist's videos.

Uses plain requests against the REST endpoint rather than the
google-api-python-client/google-auth stack -- an API-key-authenticated
playlistItems.list call doesn't need the OAuth-oriented machinery that
package brings in.
"""
from __future__ import annotations

from dataclasses import dataclass

import requests

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
PLAYLIST_ITEMS_PAGE_SIZE = 50

# YouTube replaces the title with one of these for playlist entries whose
# video has been deleted or made private. Such entries can never be
# summarized (no captions, and Gemini's direct-URL ingestion requires a
# public video), so main.py auto-skips them.
UNAVAILABLE_VIDEO_TITLES = {"Private video", "Deleted video"}


class YouTubeApiError(RuntimeError):
    """Raised when the YouTube Data API returns a non-2xx response."""


@dataclass(frozen=True)
class VideoMetadata:
    video_id: str
    title: str
    description: str
    published_at: str
    added_to_playlist_at: str
    thumbnail_url: str
    channel_title: str
    watch_url: str
    embed_url: str

    @property
    def is_unavailable(self) -> bool:
        return self.title in UNAVAILABLE_VIDEO_TITLES


def fetch_playlist_videos(
    api_key: str,
    playlist_id: str,
    *,
    session: requests.Session | None = None,
    timeout: int = 30,
) -> list[VideoMetadata]:
    """Fetches every video in the playlist, following pagination.

    Returned order matches the API's natural playlist-position order
    (ascending == oldest-added-first for a normal append-only playlist).

    Raises YouTubeApiError on any non-2xx response.
    """
    http = session if session is not None else requests
    videos: list[VideoMetadata] = []
    page_token: str | None = None

    while True:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": PLAYLIST_ITEMS_PAGE_SIZE,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        response = http.get(f"{YOUTUBE_API_BASE}/playlistItems", params=params, timeout=timeout)
        if response.status_code != 200:
            raise YouTubeApiError(
                f"YouTube API request failed with status {response.status_code}: {response.text[:500]}"
            )

        payload = response.json()
        for item in payload.get("items", []):
            videos.append(_parse_item(item))

        page_token = payload.get("nextPageToken")
        if not page_token:
            break

    return videos


def _parse_item(item: dict) -> VideoMetadata:
    snippet = item.get("snippet", {}) or {}
    content_details = item.get("contentDetails", {}) or {}
    resource_id = snippet.get("resourceId", {}) or {}

    video_id = content_details.get("videoId") or resource_id.get("videoId", "")
    added_to_playlist_at = snippet.get("publishedAt", "")

    return VideoMetadata(
        video_id=video_id,
        title=snippet.get("title", ""),
        description=snippet.get("description", ""),
        # contentDetails.videoPublishedAt (the video's own publish date) is
        # absent for some private/deleted entries -- fall back to the
        # playlist-add date so callers always get a usable timestamp.
        published_at=content_details.get("videoPublishedAt") or added_to_playlist_at,
        added_to_playlist_at=added_to_playlist_at,
        thumbnail_url=_best_thumbnail_url(snippet.get("thumbnails", {}) or {}),
        # videoOwnerChannelTitle is the video's own channel; channelTitle
        # alone is the *playlist owner's* channel, which is only the same
        # thing by coincidence. Prefer the former.
        channel_title=snippet.get("videoOwnerChannelTitle") or snippet.get("channelTitle", ""),
        watch_url=f"https://www.youtube.com/watch?v={video_id}",
        embed_url=f"https://www.youtube.com/embed/{video_id}",
    )


def _best_thumbnail_url(thumbnails: dict) -> str:
    for size in ("high", "medium", "default"):
        thumb = thumbnails.get(size)
        if thumb and thumb.get("url"):
            return thumb["url"]
    return ""
