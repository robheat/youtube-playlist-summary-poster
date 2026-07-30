"""Tests for app.youtube.fetch_playlist_videos."""
from __future__ import annotations

import pytest

from app.youtube import YouTubeApiError, fetch_playlist_videos


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text or str(json_data)

    def json(self):
        return self._json_data


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def get(self, url, params=None, timeout=None):
        self.requests.append({"url": url, "params": params, "timeout": timeout})
        return self._responses.pop(0)


def _item(video_id, title="Title", snippet=None, content_details=None):
    base_snippet = {
        "publishedAt": "2026-01-01T00:00:00Z",
        "title": title,
        "description": "desc",
        "thumbnails": {
            "high": {"url": f"https://img.example.com/{video_id}/hq.jpg"},
            "medium": {"url": f"https://img.example.com/{video_id}/mq.jpg"},
        },
        "channelTitle": "Playlist Owner Channel",
        "videoOwnerChannelTitle": "Actual Video Channel",
        "resourceId": {"kind": "youtube#video", "videoId": video_id},
    }
    base_snippet.update(snippet or {})
    base_content_details = {"videoId": video_id, "videoPublishedAt": "2025-12-25T00:00:00Z"}
    base_content_details.update(content_details or {})
    return {"snippet": base_snippet, "contentDetails": base_content_details}


def test_fetches_single_page():
    session = FakeSession([FakeResponse(json_data={"items": [_item("abc123")]})])

    videos = fetch_playlist_videos("api-key", "PL123", session=session)

    assert len(videos) == 1
    video = videos[0]
    assert video.video_id == "abc123"
    assert video.title == "Title"
    assert video.channel_title == "Actual Video Channel"
    assert video.thumbnail_url == "https://img.example.com/abc123/hq.jpg"
    assert video.watch_url == "https://www.youtube.com/watch?v=abc123"
    assert video.embed_url == "https://www.youtube.com/embed/abc123"
    assert video.published_at == "2025-12-25T00:00:00Z"


def test_follows_pagination():
    page1 = FakeResponse(json_data={"items": [_item("vid1")], "nextPageToken": "page2token"})
    page2 = FakeResponse(json_data={"items": [_item("vid2")]})
    session = FakeSession([page1, page2])

    videos = fetch_playlist_videos("api-key", "PL123", session=session)

    assert [v.video_id for v in videos] == ["vid1", "vid2"]
    assert session.requests[1]["params"]["pageToken"] == "page2token"


def test_channel_title_falls_back_to_playlist_owner_channel():
    item = _item("abc123")
    del item["snippet"]["videoOwnerChannelTitle"]
    session = FakeSession([FakeResponse(json_data={"items": [item]})])

    videos = fetch_playlist_videos("api-key", "PL123", session=session)

    assert videos[0].channel_title == "Playlist Owner Channel"


def test_thumbnail_falls_back_through_sizes():
    item = _item("abc123")
    item["snippet"]["thumbnails"] = {
        "default": {"url": "https://img.example.com/abc123/default.jpg"}
    }
    session = FakeSession([FakeResponse(json_data={"items": [item]})])

    videos = fetch_playlist_videos("api-key", "PL123", session=session)

    assert videos[0].thumbnail_url == "https://img.example.com/abc123/default.jpg"


def test_private_video_marked_unavailable():
    item = _item("abc123", title="Private video", snippet={"description": ""})
    session = FakeSession([FakeResponse(json_data={"items": [item]})])

    videos = fetch_playlist_videos("api-key", "PL123", session=session)

    assert videos[0].is_unavailable is True


def test_normal_video_not_marked_unavailable():
    session = FakeSession([FakeResponse(json_data={"items": [_item("abc123")]})])

    videos = fetch_playlist_videos("api-key", "PL123", session=session)

    assert videos[0].is_unavailable is False


def test_non_200_response_raises_youtube_api_error():
    session = FakeSession([FakeResponse(status_code=403, text="quota exceeded")])

    with pytest.raises(YouTubeApiError, match="403"):
        fetch_playlist_videos("api-key", "PL123", session=session)
