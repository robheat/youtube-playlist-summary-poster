"""Tests for app.summarize.transcript.get_transcript."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from youtube_transcript_api import CouldNotRetrieveTranscript, NoTranscriptFound

from app.summarize.transcript import TranscriptError, get_transcript


class FakeSnippet:
    def __init__(self, text):
        self.text = text


class FakeTranscript:
    def __init__(self, snippets):
        self._snippets = snippets

    def fetch(self):
        return self._snippets


class _FakeNoTranscriptFound(NoTranscriptFound):
    def __init__(self):
        pass  # skip the real __init__ -- its exact signature isn't our concern here

    def __str__(self):
        return "no transcript found"


class _FakeCouldNotRetrieveTranscript(CouldNotRetrieveTranscript):
    def __init__(self, message="blocked"):
        self._message = message

    def __str__(self):
        return self._message


class FakeTranscriptList:
    def __init__(self, by_language=None, fallback_order=None):
        self._by_language = by_language or {}
        self._fallback_order = fallback_order or []

    def find_transcript(self, language_codes):
        for code in language_codes:
            if code in self._by_language:
                return self._by_language[code]
        raise _FakeNoTranscriptFound()

    def __iter__(self):
        return iter(self._fallback_order)


def _patch_api(list_return=None, list_raises=None):
    fake_api_instance = MagicMock()
    if list_raises:
        fake_api_instance.list.side_effect = list_raises
    else:
        fake_api_instance.list.return_value = list_return
    return (
        patch("app.summarize.transcript.YouTubeTranscriptApi", return_value=fake_api_instance),
        fake_api_instance,
    )


def test_returns_english_transcript_joined_as_text():
    transcript = FakeTranscript([FakeSnippet("Hello"), FakeSnippet("world.")])
    transcript_list = FakeTranscriptList(by_language={"en": transcript})
    patcher, _ = _patch_api(list_return=transcript_list)

    with patcher:
        result = get_transcript("abc123")

    assert result == "Hello world."


def test_falls_back_to_any_language_when_preferred_unavailable():
    fallback_transcript = FakeTranscript([FakeSnippet("Bonjour"), FakeSnippet("le monde.")])
    transcript_list = FakeTranscriptList(fallback_order=[fallback_transcript])
    patcher, _ = _patch_api(list_return=transcript_list)

    with patcher:
        result = get_transcript("abc123")

    assert result == "Bonjour le monde."


def test_raises_transcript_error_when_blocked():
    patcher, _ = _patch_api(list_raises=_FakeCouldNotRetrieveTranscript("IP blocked"))

    with patcher:
        with pytest.raises(TranscriptError, match="IP blocked"):
            get_transcript("abc123")


def test_passes_proxy_config_when_credentials_given():
    transcript_list = FakeTranscriptList(by_language={"en": FakeTranscript([FakeSnippet("Hi")])})
    fake_api_instance = MagicMock()
    fake_api_instance.list.return_value = transcript_list

    with patch(
        "app.summarize.transcript.YouTubeTranscriptApi", return_value=fake_api_instance
    ) as fake_cls:
        get_transcript("abc123", proxy_username="user", proxy_password="pass")

    _, kwargs = fake_cls.call_args
    assert kwargs["proxy_config"] is not None


def test_no_proxy_config_when_credentials_absent():
    transcript_list = FakeTranscriptList(by_language={"en": FakeTranscript([FakeSnippet("Hi")])})
    fake_api_instance = MagicMock()
    fake_api_instance.list.return_value = transcript_list

    with patch(
        "app.summarize.transcript.YouTubeTranscriptApi", return_value=fake_api_instance
    ) as fake_cls:
        get_transcript("abc123")

    _, kwargs = fake_cls.call_args
    assert kwargs["proxy_config"] is None


def test_no_proxy_config_when_only_username_given():
    transcript_list = FakeTranscriptList(by_language={"en": FakeTranscript([FakeSnippet("Hi")])})
    fake_api_instance = MagicMock()
    fake_api_instance.list.return_value = transcript_list

    with patch(
        "app.summarize.transcript.YouTubeTranscriptApi", return_value=fake_api_instance
    ) as fake_cls:
        get_transcript("abc123", proxy_username="user", proxy_password=None)

    _, kwargs = fake_cls.call_args
    assert kwargs["proxy_config"] is None
