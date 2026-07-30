"""Tests for app.publish.images.download_thumbnail."""
from __future__ import annotations

import pytest
import requests

from app.publish.images import ImageDownloadError, download_thumbnail


class FakeResponse:
    def __init__(self, status_code=200, content=b""):
        self.status_code = status_code
        self.content = content


class FakeSession:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append({"url": url, "timeout": timeout})
        if self._exc:
            raise self._exc
        return self._response


def test_returns_response_content_on_success():
    session = FakeSession(response=FakeResponse(status_code=200, content=b"fake-image-bytes"))

    result = download_thumbnail("https://img.example.com/thumb.jpg", session=session)

    assert result == b"fake-image-bytes"
    assert session.calls[0]["url"] == "https://img.example.com/thumb.jpg"


def test_raises_on_non_200():
    session = FakeSession(response=FakeResponse(status_code=404))

    with pytest.raises(ImageDownloadError, match="404"):
        download_thumbnail("https://img.example.com/missing.jpg", session=session)


def test_raises_on_network_error():
    session = FakeSession(exc=requests.ConnectionError("boom"))

    with pytest.raises(ImageDownloadError):
        download_thumbnail("https://img.example.com/thumb.jpg", session=session)
