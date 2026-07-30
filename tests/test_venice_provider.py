"""Tests for app.summarize.venice.VeniceProvider."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from app.summarize.base import SummaryError
from app.summarize.transcript import TranscriptError
from app.summarize.venice import VeniceProvider


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self):
        return self._json_data


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


def _success_response(content="A concise summary."):
    return FakeResponse(status_code=200, json_data={"choices": [{"message": {"content": content}}]})


def test_summarize_sends_transcript_and_returns_content(sample_video):
    session = FakeSession(response=_success_response("  A concise summary.  "))

    with patch("app.summarize.venice.get_transcript", return_value="This is the transcript text."):
        provider = VeniceProvider(api_key="fake-key", model="some-model", session=session)
        result = provider.summarize(sample_video)

    assert result == "A concise summary."
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["headers"]["Authorization"] == "Bearer fake-key"
    assert "This is the transcript text." in call["json"]["messages"][0]["content"]
    assert call["json"]["model"] == "some-model"


def test_summarize_wraps_transcript_error(sample_video):
    with patch("app.summarize.venice.get_transcript", side_effect=TranscriptError("blocked")):
        provider = VeniceProvider(api_key="fake-key", model="some-model", session=FakeSession())
        with pytest.raises(SummaryError, match="blocked"):
            provider.summarize(sample_video)


def test_summarize_truncates_long_transcript(sample_video):
    long_transcript = "word " * 100
    session = FakeSession(response=_success_response())

    with patch("app.summarize.venice.get_transcript", return_value=long_transcript):
        provider = VeniceProvider(
            api_key="fake-key", model="some-model", session=session, max_transcript_chars=20
        )
        provider.summarize(sample_video)

    sent_content = session.calls[0]["json"]["messages"][0]["content"]
    transcript_in_prompt = sent_content.split("Transcript:\n", 1)[1]
    assert len(transcript_in_prompt) <= 20


def test_summarize_raises_on_non_200(sample_video):
    session = FakeSession(response=FakeResponse(status_code=500, text="server error"))

    with patch("app.summarize.venice.get_transcript", return_value="transcript"):
        provider = VeniceProvider(api_key="fake-key", model="some-model", session=session)
        with pytest.raises(SummaryError, match="500"):
            provider.summarize(sample_video)


def test_summarize_raises_on_malformed_response(sample_video):
    session = FakeSession(response=FakeResponse(status_code=200, json_data={"unexpected": "shape"}))

    with patch("app.summarize.venice.get_transcript", return_value="transcript"):
        provider = VeniceProvider(api_key="fake-key", model="some-model", session=session)
        with pytest.raises(SummaryError, match="Unexpected Venice response"):
            provider.summarize(sample_video)


def test_summarize_raises_on_network_error(sample_video):
    session = FakeSession(exc=requests.ConnectionError("boom"))

    with patch("app.summarize.venice.get_transcript", return_value="transcript"):
        provider = VeniceProvider(api_key="fake-key", model="some-model", session=session)
        with pytest.raises(SummaryError):
            provider.summarize(sample_video)


def test_summarize_raises_on_empty_content(sample_video):
    session = FakeSession(response=_success_response(content="   "))

    with patch("app.summarize.venice.get_transcript", return_value="transcript"):
        provider = VeniceProvider(api_key="fake-key", model="some-model", session=session)
        with pytest.raises(SummaryError, match="empty"):
            provider.summarize(sample_video)
