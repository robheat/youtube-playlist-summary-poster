"""Tests for app.summarize.gemini.GeminiProvider.

Gemini's native YouTube video-URL ingestion was tried and abandoned after
live testing (see gemini.py's docstring) -- this provider is now
transcript-based, structurally mirroring VeniceProvider, just against the
Gemini API instead.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.summarize.base import ArticleContent, SummaryError
from app.summarize.gemini import GeminiProvider
from app.summarize.transcript import TranscriptError

VALID_ARTICLE_JSON = json.dumps(
    {
        "title": "A Great Video Title",
        "summary": "A one-sentence standfirst.",
        "body": "Paragraph one.\n\nParagraph two.",
        "category": "news",
        "tags": ["tag-one", "tag-two"],
    }
)


class FakeGenerateContentResponse:
    def __init__(self, text):
        self.text = text


def _make_provider(response_text=VALID_ARTICLE_JSON, raise_exc=None, **kwargs):
    fake_client = MagicMock()
    if raise_exc:
        fake_client.models.generate_content.side_effect = raise_exc
    else:
        fake_client.models.generate_content.return_value = FakeGenerateContentResponse(
            response_text
        )

    with patch("app.summarize.gemini.genai.Client", return_value=fake_client):
        provider = GeminiProvider(api_key="fake-key", model="gemini-2.5-flash", **kwargs)
    return provider, fake_client


def test_generate_article_returns_parsed_content(sample_video, sample_site_profile):
    provider, _ = _make_provider()

    with patch("app.summarize.gemini.get_transcript", return_value="This is the transcript."):
        result = provider.generate_article(sample_video, sample_site_profile)

    assert isinstance(result, ArticleContent)
    assert result.title == "A Great Video Title"
    assert result.category == "news"
    assert result.tags == ["tag-one", "tag-two"]


def test_generate_article_sends_model_and_transcript(sample_video, sample_site_profile):
    provider, fake_client = _make_provider()

    with patch(
        "app.summarize.gemini.get_transcript", return_value="This is the transcript text."
    ):
        provider.generate_article(sample_video, sample_site_profile)

    _, kwargs = fake_client.models.generate_content.call_args
    assert kwargs["model"] == "gemini-2.5-flash"
    assert "This is the transcript text." in kwargs["contents"][0]


def test_generate_article_prompt_includes_site_categories(sample_video, sample_site_profile):
    provider, fake_client = _make_provider()

    with patch("app.summarize.gemini.get_transcript", return_value="transcript"):
        provider.generate_article(sample_video, sample_site_profile)

    _, kwargs = fake_client.models.generate_content.call_args
    prompt_text = kwargs["contents"][0]
    for category in sample_site_profile.categories:
        assert category in prompt_text


def test_generate_article_truncates_long_transcript(sample_video, sample_site_profile):
    provider, fake_client = _make_provider(max_transcript_chars=20)
    long_transcript = "word " * 100

    with patch("app.summarize.gemini.get_transcript", return_value=long_transcript):
        provider.generate_article(sample_video, sample_site_profile)

    _, kwargs = fake_client.models.generate_content.call_args
    sent_prompt = kwargs["contents"][0]
    transcript_in_prompt = sent_prompt.split("Transcript:\n", 1)[1]
    assert len(transcript_in_prompt) <= 20


def test_generate_article_wraps_transcript_error(sample_video, sample_site_profile):
    provider, _ = _make_provider()

    with patch("app.summarize.gemini.get_transcript", side_effect=TranscriptError("blocked")):
        with pytest.raises(SummaryError, match="blocked"):
            provider.generate_article(sample_video, sample_site_profile)


def test_generate_article_raises_on_empty_response(sample_video, sample_site_profile):
    provider, _ = _make_provider(response_text="   ")

    with patch("app.summarize.gemini.get_transcript", return_value="transcript"):
        with pytest.raises(SummaryError, match="empty"):
            provider.generate_article(sample_video, sample_site_profile)


def test_generate_article_raises_on_malformed_json(sample_video, sample_site_profile):
    provider, _ = _make_provider(response_text="not json at all")

    with patch("app.summarize.gemini.get_transcript", return_value="transcript"):
        with pytest.raises(SummaryError):
            provider.generate_article(sample_video, sample_site_profile)


def test_generate_article_wraps_client_exception(sample_video, sample_site_profile):
    provider, _ = _make_provider(raise_exc=RuntimeError("network down"))

    with patch("app.summarize.gemini.get_transcript", return_value="transcript"):
        with pytest.raises(SummaryError, match="network down"):
            provider.generate_article(sample_video, sample_site_profile)
