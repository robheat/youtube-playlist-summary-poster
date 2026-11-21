"""Tests for app.summarize.article_json: prompt building and response
validation shared by both providers."""
from __future__ import annotations

import dataclasses
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


# --- optional fields and internal links ---------------------------------------

ALL_EXTRAS = frozenset({"seoTitle", "metaDescription", "keyTakeaways", "faq", "entities"})

EXTRAS_PAYLOAD = {
    **VALID_PAYLOAD,
    "seoTitle": "  A Search   Title  ",
    "metaDescription": "M" * 300,
    "keyTakeaways": [
        "- **OpenAI** released a model that runs on a single consumer GPU.",
        "Too short.",
        42,
    ],
    "faq": [
        {"question": "Is it free to use", "answer": "Yes, under an open licence."},
        {"question": "No answer here?"},
        "not an object",
    ],
    "entities": [
        {"name": "OpenAI", "type": "Organization", "sameAs": "https://en.wikipedia.org/wiki/OpenAI"},
        {"name": "openai", "type": "Organization"},
        {"name": "GPT-9", "type": "Spaceship", "sameAs": "https://example.com/gpt-9"},
    ],
}


def test_build_json_instructions_includes_only_the_sites_extra_fields(sample_site_profile):
    profile = dataclasses.replace(sample_site_profile, extra_fields=frozenset({"faq"}))
    instructions = build_json_instructions(profile)
    assert '"faq"' in instructions
    assert '"keyTakeaways"' not in instructions
    assert '"seoTitle"' not in instructions


def test_build_json_instructions_omits_extras_and_links_by_default(sample_site_profile):
    instructions = build_json_instructions(sample_site_profile)
    for key in ALL_EXTRAS:
        assert f'"{key}"' not in instructions
    assert "related_articles" not in instructions


def test_build_json_instructions_includes_related_articles_when_given(sample_site_profile):
    related = [{"slug": "uniswap-v4", "title": "Uniswap V4", "summary": "About v4."}]
    instructions = build_json_instructions(sample_site_profile, related)
    assert "/articles/<slug>" in instructions
    assert '"slug": "uniswap-v4"' in instructions


def test_build_json_instructions_omits_link_block_for_empty_related(sample_site_profile):
    assert "related_articles" not in build_json_instructions(sample_site_profile, [])


def test_parse_article_normalizes_extras_and_drops_malformed_entries(sample_site_profile):
    profile = dataclasses.replace(sample_site_profile, extra_fields=ALL_EXTRAS)
    article = parse_article(json.dumps(EXTRAS_PAYLOAD), profile, "vid123")

    assert article.seo_title == "A Search Title"
    assert article.meta_description == "M" * 180
    assert article.key_takeaways == ["OpenAI released a model that runs on a single consumer GPU."]
    assert article.faq == [{"question": "Is it free to use?", "answer": "Yes, under an open licence."}]
    assert article.entities == [
        {"name": "OpenAI", "type": "Organization", "sameAs": "https://en.wikipedia.org/wiki/OpenAI"},
        {"name": "GPT-9", "type": "Thing"},
    ]


def test_parse_article_ignores_extras_the_site_did_not_ask_for(sample_site_profile):
    article = parse_article(json.dumps(EXTRAS_PAYLOAD), sample_site_profile, "vid123")
    assert article.seo_title == ""
    assert article.key_takeaways == []
    assert article.faq == []
    assert article.entities == []


def test_parse_article_malformed_extras_never_fail_the_video(sample_site_profile):
    profile = dataclasses.replace(sample_site_profile, extra_fields=ALL_EXTRAS)
    payload = {
        **VALID_PAYLOAD,
        "seoTitle": ["not", "a", "string"],
        "keyTakeaways": "not a list",
        "faq": {"question": "q", "answer": "a"},
        "entities": None,
    }
    article = parse_article(json.dumps(payload), profile, "vid123")
    assert article.seo_title == ""
    assert article.key_takeaways == []
    assert article.faq == []
    assert article.entities == []
