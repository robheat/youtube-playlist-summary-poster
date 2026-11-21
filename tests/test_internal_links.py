"""Tests for app.summarize.internal_links: which existing articles get
offered as link targets, and which links in a generated body survive."""
from __future__ import annotations

import dataclasses

from app.summarize.internal_links import (
    corpus_entry,
    related_payload,
    sanitize_internal_links,
    select_link_candidates,
)


def _article(slug, tags, title="Unrelated Headline Words", **extra):
    return {
        "slug": slug,
        "title": title,
        "category": "general",
        "tags": tags,
        "summary": "An existing article.",
        "publishedAt": "2026-01-01T00:00:00Z",
        "sourceUrl": f"https://example.com/{slug}",
        **extra,
    }


def _filler(n=200):
    # Scoring weights shared terms by rarity, log(N/df), against a
    # threshold calibrated on a real site's corpus -- so a single shared
    # tag only clears it once the corpus is a realistic size.
    return [_article(f"filler-{i}", [f"filler-tag-{i}"]) for i in range(n)]


def _video(sample_video, title, description=""):
    return dataclasses.replace(sample_video, title=title, description=description)


# --- select_link_candidates -------------------------------------------------


def test_rare_word_in_headline_and_tag_is_offered(sample_video, sample_site_profile):
    corpus = _filler() + [_article("uniswap-v4", ["uniswap"], title="Uniswap V4 Hooks Go Live")]
    video = _video(sample_video, "Uniswap governance vote explained")

    result = select_link_candidates(video, corpus, sample_site_profile)

    assert [c["slug"] for c in result] == ["uniswap-v4"]


def test_single_word_tag_match_alone_is_not_enough(sample_video, sample_site_profile):
    # A real false positive: "Base Case" matched articles about Coinbase's
    # Base network, tagged "base", when single words matched tags at full weight.
    corpus = _filler() + [_article("base-tvl", ["base"])]
    video = _video(sample_video, "$120K Isn't The Bitcoin Bull Case. It's The Base Case.")

    assert select_link_candidates(video, corpus, sample_site_profile) == []


def test_hyphenated_word_pair_matches_tag(sample_video, sample_site_profile):
    corpus = _filler() + [_article("open-weights", ["open-source"])]
    video = _video(sample_video, "Why open source matters")

    result = select_link_candidates(video, corpus, sample_site_profile)

    assert [c["slug"] for c in result] == ["open-weights"]


def test_ubiquitous_tag_is_not_evidence(sample_video, sample_site_profile):
    # "stablecoins" on every article is background, not a relationship.
    corpus = [_article(f"a-{i}", ["stablecoins"]) for i in range(40)]
    video = _video(sample_video, "Stablecoins weekly roundup")

    assert select_link_candidates(video, corpus, sample_site_profile) == []


def test_article_from_the_same_video_is_excluded(sample_video, sample_site_profile):
    corpus = _filler() + [
        _article("same-video", ["uniswap"], sourceUrl=sample_video.watch_url),
    ]
    video = _video(sample_video, "Uniswap governance vote explained")

    assert select_link_candidates(video, corpus, sample_site_profile) == []


def test_digest_articles_are_excluded(sample_video, sample_site_profile):
    corpus = _filler() + [_article("brief", ["uniswap", "morning-brief"])]
    video = _video(sample_video, "Uniswap governance vote explained")

    assert select_link_candidates(video, corpus, sample_site_profile) == []


def test_description_words_count_but_urls_do_not(sample_video, sample_site_profile):
    corpus = _filler() + [
        _article("uniswap-v4", ["uniswap"], title="Uniswap V4 Hooks Go Live"),
        _article("patreon", ["patreon"], title="Patreon Adds Crypto Payouts"),
    ]
    video = _video(
        sample_video,
        "Weekly market roundup",
        description="We cover Uniswap. Support us: https://patreon.com/somechannel",
    )

    result = select_link_candidates(video, corpus, sample_site_profile)

    assert [c["slug"] for c in result] == ["uniswap-v4"]


def test_limit_caps_candidates(sample_video, sample_site_profile):
    corpus = _filler() + [
        _article(f"uni-{i}", ["uniswap"], title=f"Uniswap Governance Story {i}") for i in range(5)
    ]
    video = _video(sample_video, "Uniswap governance vote explained")

    assert len(select_link_candidates(video, corpus, sample_site_profile, limit=3)) == 3


def test_empty_corpus_offers_nothing(sample_video, sample_site_profile):
    assert select_link_candidates(sample_video, [], sample_site_profile) == []


def test_site_link_stopwords_are_ignored(sample_video, sample_site_profile):
    profile = dataclasses.replace(sample_site_profile, link_stopwords=("uniswap",))
    corpus = _filler() + [_article("uniswap-v4", ["uniswap"], title="Uniswap V4 Hooks Go Live")]
    video = _video(sample_video, "Uniswap governance vote explained")

    assert select_link_candidates(video, corpus, profile) == []


def test_related_payload_trims_to_prompt_fields():
    payload = related_payload([_article("x", ["t"], summary="s" * 500)])
    assert payload == [{"slug": "x", "title": "Unrelated Headline Words", "summary": "s" * 240}]


def test_corpus_entry_tolerates_missing_fields():
    entry = corpus_entry({"slug": "only-slug"})
    assert entry["slug"] == "only-slug"
    assert entry["tags"] == []
    assert entry["category"] == "general"


# --- sanitize_internal_links -------------------------------------------------

UNISWAP = _article("uniswap-fee-switch", ["uniswap", "governance"], title="Uniswap Fee Switch Vote")
AAVE = _article("aave-v4", ["aave", "lending"], title="Aave V4 Launch Date")


def test_offered_link_with_descriptive_anchor_is_kept(sample_site_profile):
    body = "The [Uniswap fee vote](/articles/uniswap-fee-switch) passed."
    result, kept = sanitize_internal_links(body, [UNISWAP], sample_site_profile)
    assert result == body
    assert kept == ["uniswap-fee-switch"]


def test_invented_slug_is_unwrapped(sample_site_profile):
    body = "The [Uniswap fee vote](/articles/not-offered) passed."
    result, kept = sanitize_internal_links(body, [UNISWAP], sample_site_profile)
    assert result == "The Uniswap fee vote passed."
    assert kept == []


def test_tag_category_and_external_links_are_unwrapped(sample_site_profile):
    body = (
        "More [Uniswap news](/tags/uniswap), our [DeFi section](/categories/defi), "
        "and [the video](https://youtube.com/watch?v=x)."
    )
    result, kept = sanitize_internal_links(body, [UNISWAP], sample_site_profile)
    assert result == "More Uniswap news, our DeFi section, and the video."
    assert kept == []


def test_vague_anchor_is_unwrapped(sample_site_profile):
    body = "Read more [here](/articles/uniswap-fee-switch)."
    result, kept = sanitize_internal_links(body, [UNISWAP], sample_site_profile)
    assert result == "Read more here."
    assert kept == []


def test_second_link_to_same_target_is_unwrapped(sample_site_profile):
    body = (
        "The [Uniswap vote](/articles/uniswap-fee-switch) passed.\n\n"
        "The [fee switch](/articles/uniswap-fee-switch) turns on next month."
    )
    result, kept = sanitize_internal_links(body, [UNISWAP], sample_site_profile)
    assert result.endswith("The fee switch turns on next month.")
    assert kept == ["uniswap-fee-switch"]


def test_links_are_capped(sample_site_profile):
    candidates = [
        _article(f"uni-{i}", ["uniswap"], title=f"Uniswap Story {i}") for i in range(5)
    ]
    body = "\n\n".join(f"[Uniswap story {i}](/articles/uni-{i})" for i in range(5))
    result, kept = sanitize_internal_links(body, candidates, sample_site_profile, max_links=3)
    assert kept == ["uni-0", "uni-1", "uni-2"]
    assert result.endswith("Uniswap story 3\n\nUniswap story 4")


def test_links_in_subheadings_are_unwrapped(sample_site_profile):
    body = "## What the [Uniswap vote](/articles/uniswap-fee-switch) means\n\nText."
    result, kept = sanitize_internal_links(body, [UNISWAP], sample_site_profile)
    assert result == "## What the Uniswap vote means\n\nText."
    assert kept == []


def test_multiple_different_targets_are_kept(sample_site_profile):
    body = (
        "The [Uniswap fee vote](/articles/uniswap-fee-switch) passed.\n\n"
        "Meanwhile [Aave's next version](/articles/aave-v4) nears launch."
    )
    result, kept = sanitize_internal_links(body, [UNISWAP, AAVE], sample_site_profile)
    assert result == body
    assert kept == ["uniswap-fee-switch", "aave-v4"]
