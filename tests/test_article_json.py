"""Tests for app.summarize.article_json: prompt building and response
validation shared by both providers."""
from __future__ import annotations

import json

import pytest

from app.summarize.article_json import build_json_instructions, extract_json, parse_article
from app.summarize.base import SummaryError

VALID_PAYLOAD = {
    "title": "A Great Video Title",
    "summary": "A one-sentence standfirst.",
    "body": "Paragraph one.\n\nParagraph two.",
    "category": "news",
    "tags": ["Tag One", "tag-two"],
}


def test_build_json_instructions_lists_site_categories(sample_site_profile):
    instructions = build_json_instructions(sample_site_profile)
    for category in sample_site_profile.categories:
        assert category in instructions


def test_extract_json_parses_raw_object():
    assert extract_json(json.dumps(VALID_PAYLOAD)) == VALID_PAYLOAD


def test_extract_json_strips_markdown_fence():
    fenced = f"```json\n{json.dumps(VALID_PAYLOAD)}\n```"
    assert extract_json(fenced) == VALID_PAYLOAD


def test_extract_json_strips_surrounding_commentary():
    wrapped = f"Sure, here's the article:\n{json.dumps(VALID_PAYLOAD)}\nHope that helps!"
    assert extract_json(wrapped) == VALID_PAYLOAD


def test_parse_article_returns_expected_fields(sample_site_profile):
    article = parse_article(json.dumps(VALID_PAYLOAD), sample_site_profile, "vid123")
    assert article.title == "A Great Video Title"
    assert article.summary == "A one-sentence standfirst."
    assert article.category == "news"


def test_parse_article_lowercases_and_hyphenates_tags(sample_site_profile):
    article = parse_article(json.dumps(VALID_PAYLOAD), sample_site_profile, "vid123")
    assert article.tags == ["tag-one", "tag-two"]


def test_parse_article_falls_back_to_general_on_invalid_category(sample_site_profile):
    payload = {**VALID_PAYLOAD, "category": "not-a-real-category"}
    article = parse_article(json.dumps(payload), sample_site_profile, "vid123")
    assert article.category == "general"


@pytest.mark.parametrize("missing_key", ["title", "summary", "body", "category"])
def test_parse_article_raises_on_missing_required_field(sample_site_profile, missing_key):
    payload = dict(VALID_PAYLOAD)
    del payload[missing_key]
    with pytest.raises(SummaryError, match=missing_key):
        parse_article(json.dumps(payload), sample_site_profile, "vid123")


def test_parse_article_raises_on_empty_required_field(sample_site_profile):
    payload = {**VALID_PAYLOAD, "title": "   "}
    with pytest.raises(SummaryError, match="title"):
        parse_article(json.dumps(payload), sample_site_profile, "vid123")


def test_parse_article_raises_on_missing_tags(sample_site_profile):
    payload = dict(VALID_PAYLOAD)
    del payload["tags"]
    with pytest.raises(SummaryError, match="tags"):
        parse_article(json.dumps(payload), sample_site_profile, "vid123")


def test_parse_article_raises_on_empty_tags_list(sample_site_profile):
    payload = {**VALID_PAYLOAD, "tags": []}
    with pytest.raises(SummaryError, match="tags"):
        parse_article(json.dumps(payload), sample_site_profile, "vid123")


def test_parse_article_raises_on_non_object_json(sample_site_profile):
    with pytest.raises(SummaryError):
        parse_article(json.dumps(["not", "an", "object"]), sample_site_profile, "vid123")


def test_parse_article_raises_on_unparseable_text(sample_site_profile):
    with pytest.raises(SummaryError):
        parse_article("this is not json", sample_site_profile, "vid123")
