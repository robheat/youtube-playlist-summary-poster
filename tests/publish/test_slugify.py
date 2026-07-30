"""Tests for app.publish.slugify -- ported from ainformed-dev's lib/utils.ts."""
from __future__ import annotations

from app.publish.slugify import slugify


def test_matches_real_site_example():
    # Verified against the real published slug
    # "2026-05-08-bitcoin-nears-85k-resistance-as-etf-inflows-surge.json"
    assert (
        slugify("Bitcoin Nears $85K Resistance as ETF Inflows Surge")
        == "bitcoin-nears-85k-resistance-as-etf-inflows-surge"
    )


def test_lowercases():
    assert slugify("HELLO World") == "hello-world"


def test_collapses_whitespace_runs_to_single_hyphen():
    assert slugify("hello    world") == "hello-world"


def test_collapses_hyphen_runs():
    assert slugify("hello--world") == "hello-world"


def test_strips_punctuation():
    assert slugify("What's New: AI, Robots & More!") == "whats-new-ai-robots-more"


def test_forces_ascii_word_semantics_unlike_python_default_unicode_w():
    # Python's bare \w is Unicode-aware and would KEEP accented letters;
    # JS's \w is ASCII-only and strips them. This must match the JS side.
    assert slugify("Café résumé naïve") == "caf-rsum-nave"


def test_leading_and_trailing_whitespace_becomes_hyphens_not_trimmed():
    # Whitespace->hyphen conversion happens BEFORE the final trim (matching
    # the JS original's `.replace(/\s+/g, "-")` then `.trim()` order), so a
    # leading/trailing space becomes a leading/trailing hyphen, not nothing
    # -- `.trim()` only ever strips whitespace, never hyphens.
    assert slugify("  hello world  ") == "-hello-world-"
