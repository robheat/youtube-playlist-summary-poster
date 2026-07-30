"""Tests for app.summarize.gemini.GeminiProvider."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.summarize.base import SummaryError
from app.summarize.gemini import GeminiProvider


class FakeGenerateContentResponse:
    def __init__(self, text):
        self.text = text


def _make_provider(response_text="A concise summary.", raise_exc=None):
    fake_client = MagicMock()
    if raise_exc:
        fake_client.models.generate_content.side_effect = raise_exc
    else:
        fake_client.models.generate_content.return_value = FakeGenerateContentResponse(
            response_text
        )

    with patch("app.summarize.gemini.genai.Client", return_value=fake_client):
        provider = GeminiProvider(api_key="fake-key", model="gemini-2.5-flash")
    return provider, fake_client


def test_summarize_returns_trimmed_text(sample_video):
    provider, _ = _make_provider(response_text="  A concise summary.  ")

    result = provider.summarize(sample_video)

    assert result == "A concise summary."


def test_summarize_sends_model_and_watch_url(sample_video):
    provider, fake_client = _make_provider()

    provider.summarize(sample_video)

    _, kwargs = fake_client.models.generate_content.call_args
    assert kwargs["model"] == "gemini-2.5-flash"
    contents = kwargs["contents"]
    file_uris = [
        part.file_data.file_uri
        for part in contents
        if getattr(part, "file_data", None) is not None
    ]
    assert sample_video.watch_url in file_uris


def test_summarize_raises_on_empty_response(sample_video):
    provider, _ = _make_provider(response_text="   ")

    with pytest.raises(SummaryError, match="empty"):
        provider.summarize(sample_video)


def test_summarize_wraps_client_exception(sample_video):
    provider, _ = _make_provider(raise_exc=RuntimeError("network down"))

    with pytest.raises(SummaryError, match="network down"):
        provider.summarize(sample_video)
