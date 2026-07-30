"""Tests for app.publisher."""
from __future__ import annotations

import pytest
import requests

from app.publisher import PublishError, build_payload, publish_video


class FakeResponse:
    def __init__(self, status_code=200, text="", ok=None):
        self.status_code = status_code
        self.text = text
        self.ok = ok if ok is not None else 200 <= status_code < 300


class FakeSession:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if self._exc:
            raise self._exc
        return self._response


def test_build_payload_shape(sample_video):
    payload = build_payload(sample_video, "A great summary.")
    assert payload["video_id"] == sample_video.video_id
    assert payload["title"] == sample_video.title
    assert payload["url"] == sample_video.watch_url
    assert payload["embed_url"] == sample_video.embed_url
    assert payload["summary"] == "A great summary."


def test_publish_video_sends_expected_request(sample_video):
    session = FakeSession(response=FakeResponse(status_code=200))

    publish_video(
        "https://example.com/api/videos",
        "secret-key",
        sample_video,
        "Summary text",
        session=session,
    )

    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == "https://example.com/api/videos"
    assert call["headers"]["Authorization"] == "Bearer secret-key"
    assert call["json"]["video_id"] == sample_video.video_id
    assert call["json"]["summary"] == "Summary text"


def test_publish_video_raises_on_non_2xx(sample_video):
    session = FakeSession(response=FakeResponse(status_code=500, text="server error"))

    with pytest.raises(PublishError, match="500"):
        publish_video(
            "https://example.com/api/videos", "secret-key", sample_video, "Summary", session=session
        )


def test_publish_video_raises_on_network_error(sample_video):
    session = FakeSession(exc=requests.ConnectionError("boom"))

    with pytest.raises(PublishError):
        publish_video(
            "https://example.com/api/videos", "secret-key", sample_video, "Summary", session=session
        )
