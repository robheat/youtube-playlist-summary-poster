"""In-body internal links: choose which already-published articles to offer
the model as link targets, then strip any link it writes that wasn't offered.

Ported from cryptocatalyst-news's pipeline/generate_content.py (whose
scoring thresholds were calibrated by hand against that site's real
articles), so articles from this tool link the same way the sites' own
articles do. Differences from the original:

  - The "story" here is a YouTube video before any article exists, so it
    has no tags yet. Its title/description words are therefore also
    matched against candidates' TAGS, not only their headline words: a
    two-word phrase matching a hyphenated tag ("clarity-act") at full
    weight, a single word matching a single-word tag at headline-word
    weight (checked against real playlist titles: at full weight "Base
    Case" pulled in articles about the Base network).
  - The sanitizer unwraps every link that isn't an offered /articles/ slug,
    including external ones -- the prompt never asks for any other kind,
    so anything else is the model improvising a URL.
"""
from __future__ import annotations

import math
import re

from app.config import SiteProfile
from app.youtube import VideoMetadata

# Headline words that look specific but say nothing about what a story is
# about. Site-specific topic words live in SiteProfile.link_stopwords.
_BASE_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "will", "after",
    "over", "into", "amid", "says", "said", "new", "its", "his", "her",
    "their", "than", "more", "less", "but", "not", "how", "why", "what",
    "when", "who", "can", "could", "would", "should", "may", "might",
    "reveals", "faces", "challenges", "impact", "launches", "launch", "hits",
    "sees", "surges", "drops", "report", "reports", "outlines", "update",
    "updates", "plans", "record", "first", "week", "year", "billion", "million",
    "just", "now", "back", "ahead", "calls", "claims", "warns", "boost",
    "expands", "expand", "announces", "unveils", "debuts", "introduces", "adds",
    # YouTube title/description boilerplate.
    "video", "videos", "channel", "subscribe", "episode", "watch", "today",
    "full", "live", "podcast", "interview", "explained", "breaking", "news",
    "here", "about", "your", "you", "everything", "need", "know",
}

# Short market blurbs, not destinations worth a contextual link; their
# shared boilerplate tags would otherwise outscore real matches.
_EXCLUDED_TAGS = {"morning-brief", "digest", "weekly-recap"}
# A term on more than this share of the corpus is background, not evidence.
_MAX_DF_SHARE = 0.05
# Headline words are noisier than tags (tags are chosen as topics).
_TITLE_WEIGHT = 0.5
# Minimum relevance for a candidate to be offered at all. Each shared term
# scores its rarity, log(N/df): a rare shared tag is worth ~6, a moderately
# common one ~3.5, and anything on more than 5% of articles nothing.
MIN_LINK_SCORE = 5.0

MAX_LINKS = 3

_URL_RE = re.compile(r"https?://\S+")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]*)\)")
_HEADING_RE = re.compile(r"^#{1,6}\s.*$", re.M)


def corpus_entry(data: dict) -> dict:
    """The slice of a stored article JSON that link selection needs."""
    return {
        "slug": str(data.get("slug", "")),
        "title": str(data.get("title", "")),
        "category": str(data.get("category", "general")),
        "tags": [str(t) for t in data.get("tags") or []],
        "summary": str(data.get("summary", "")),
        "publishedAt": str(data.get("publishedAt", "")),
        "sourceUrl": str(data.get("sourceUrl", "")),
    }


def _stopwords(site_profile: SiteProfile) -> set[str]:
    return _BASE_STOPWORDS | set(site_profile.link_stopwords)


def _words(text: str, stopwords: set[str]) -> list[str]:
    text = _URL_RE.sub(" ", text.lower())
    words = (w.strip("-") for w in re.sub(r"[^\w\s-]", " ", text).split())
    return [w for w in words if len(w) > 3 and w not in stopwords]


def _normalize_tag(raw: str) -> str:
    """Mirror of normalizeTag() in the sites' lib/tags.ts, minus aliases."""
    base = raw.lower().strip().lstrip("#")
    base = re.sub(r"[^\w\s-]", "", base)
    base = re.sub(r"[\s_]+", "-", base)
    return re.sub(r"-+", "-", base).strip("-")


def _tag_term(tag: str) -> str:
    """Namespace for a tag: "t:" for multi-word (hyphenated) tags, "u:" for
    single-word ones, which only ever match a single video word -- weak
    evidence, weighted like a headline word."""
    return f"t:{tag}" if "-" in tag else f"u:{tag}"


def _candidate_terms(candidate: dict, stopwords: set[str]) -> set[str]:
    """Headline words and tags, namespaced so the word "defi" and the tag
    "defi" are counted as separate pieces of evidence."""
    words = {f"w:{w}" for w in _words(candidate.get("title", ""), stopwords)}
    tags = {_normalize_tag(t) for t in candidate.get("tags") or []}
    return words | {_tag_term(t) for t in tags if t}


def _video_terms(video: VideoMetadata, stopwords: set[str]) -> set[str]:
    words = _words(f"{video.title} {video.description[:300]}", stopwords)
    # Each word, and each adjacent pair joined with a hyphen ("clarity-act",
    # "open-source"), may also match a candidate's tag. Single words are
    # weak evidence here -- "Base Case" is not about the Base network, "Hedge
    # Fund" not about tokenized funds -- so they're marked for title weight
    # (see _term_weight); a two-word phrase matching a tag is specific
    # enough for full weight.
    pairs = [f"{a}-{b}" for a, b in zip(words, words[1:])]
    return {f"w:{w}" for w in words} | {_tag_term(t) for t in words + pairs}


def _term_weight(term: str) -> float:
    return 1.0 if term.startswith("t:") else _TITLE_WEIGHT


def select_link_candidates(
    video: VideoMetadata, corpus: list[dict], site_profile: SiteProfile, limit: int = 6
) -> list[dict]:
    """Pick already-published articles worth offering as internal links.
    Terms are weighted by rarity across the corpus, so a tag on a third of
    the site doesn't make everything look related, and anything below
    MIN_LINK_SCORE is left out -- the model is told a forced link is worse
    than none, so near-miss candidates mostly produced no link anyway."""
    stopwords = _stopwords(site_profile)
    story_terms = _video_terms(video, stopwords)
    if not story_terms or not corpus:
        return []

    candidate_terms = [(c, _candidate_terms(c, stopwords)) for c in corpus]
    df: dict[str, int] = {}
    for _, terms in candidate_terms:
        for term in terms & story_terms:
            df[term] = df.get(term, 0) + 1
    n = len(corpus)

    scored = []
    for candidate, terms in candidate_terms:
        if not candidate.get("slug"):
            continue
        # The same video already published (e.g. re-added to the playlist).
        if candidate.get("sourceUrl") == video.watch_url:
            continue
        if {_normalize_tag(t) for t in candidate.get("tags") or []} & _EXCLUDED_TAGS:
            continue
        shared = terms & story_terms
        if not shared:
            continue
        score = sum(
            math.log(n / df[t]) * _term_weight(t) for t in shared if df[t] <= _MAX_DF_SHARE * n
        )
        if score >= MIN_LINK_SCORE:
            scored.append((score, candidate.get("publishedAt", ""), candidate))

    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [c for _, _, c in scored[:limit]]


def related_payload(candidates: list[dict]) -> list[dict]:
    """What the model sees of each candidate. The summary lets it judge
    relevance and write an anchor from what the article is about, rather
    than paraphrasing a headline."""
    return [
        {"slug": c["slug"], "title": c["title"], "summary": c.get("summary", "")[:240]}
        for c in candidates
    ]


def _anchor_stems(text: str, stopwords: set[str]) -> set[str]:
    """Five-letter prefixes so "revisions" meets "Revised"; 3-letter words
    kept for acronyms like SEC, ETF, DAO."""
    words = re.sub(r"[^\w\s]", " ", text.lower().replace("-", " ")).split()
    return {w[:5] for w in words if len(w) >= 3 and w not in stopwords}


def anchor_describes(anchor: str, target: dict, site_profile: SiteProfile) -> bool:
    """Whether a link's anchor text names something the target is about.
    Rejects "here" / "more on this" and loosely themed anchors."""
    stopwords = _stopwords(site_profile)
    about = f"{target.get('title', '')} {' '.join(target.get('tags') or [])}"
    return bool(_anchor_stems(anchor, stopwords) & _anchor_stems(about, stopwords))


def sanitize_internal_links(
    body: str, candidates: list[dict], site_profile: SiteProfile, max_links: int = MAX_LINKS
) -> tuple[str, list[str]]:
    """Keep only links to an offered /articles/<slug> whose anchor describes
    the target, at most one per target and per anchor text, capped at
    max_links, and never inside a subheading. Every other markdown link is
    unwrapped to its anchor text. Returns (body, kept slugs in order)."""
    targets = {c["slug"]: c for c in candidates}
    kept: list[str] = []
    seen_anchors: set[str] = set()

    # A link inside a subheading reads as navigation, not a citation.
    body = _HEADING_RE.sub(lambda m: _MARKDOWN_LINK_RE.sub(r"\1", m.group(0)), body)

    def replace(match: re.Match) -> str:
        text, href = match.group(1), match.group(2).strip()
        slug = href.removeprefix("/articles/") if href.startswith("/articles/") else None
        anchor = text.strip().lower()
        if (
            slug in targets
            and slug not in kept
            and anchor not in seen_anchors
            and len(kept) < max_links
            and anchor_describes(text, targets[slug], site_profile)
        ):
            kept.append(slug)
            seen_anchors.add(anchor)
            return match.group(0)
        return text

    return _MARKDOWN_LINK_RE.sub(replace, body), kept
