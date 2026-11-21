"""Shared JSON-response contract used by both summary providers, so the
category taxonomy and validation rules exist in exactly one place and both
providers behave identically.
"""
from __future__ import annotations

import json
import logging
import re

from app.config import SiteProfile
from app.summarize.base import ArticleContent, SummaryError

logger = logging.getLogger(__name__)

REQUIRED_STRING_KEYS = ("title", "summary", "body", "category")

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# Prompt line for each optional field a SiteProfile can opt into via
# extra_fields. Wording follows each site's own pipeline/generate_content.py
# so these articles match the ones the sites generate themselves. Ordered
# so the prompt is deterministic regardless of frozenset iteration order.
EXTRA_FIELD_INSTRUCTIONS: tuple[tuple[str, str], ...] = (
    (
        "seoTitle",
        "a search-result title, 50-70 characters, with the primary "
        "entity/keyword as early as possible. Equal to title is fine if "
        "title already does this. No clickbait",
    ),
    (
        "metaDescription",
        "a search-result snippet, 120-160 characters, that states the "
        "concrete news and naturally includes the primary entity/keyword. "
        "Do not just truncate the summary",
    ),
    (
        "keyTakeaways",
        "a JSON array of 3-5 strings. Each is ONE self-contained factual "
        "sentence (max 25 words, no markdown) that makes sense with no "
        "surrounding context, with the specific name or number where the "
        "source gives one. No speculation or filler like 'This is significant'",
    ),
    (
        "faq",
        'a JSON array of 2-4 {"question": string, "answer": string} objects. '
        "Questions phrased the way a real person would type them into a "
        "search box, not restatements of the headline. Answers are 1-3 "
        "sentences (max 60 words), answering in the first sentence; if the "
        "source doesn't answer the question, say so plainly",
    ),
    (
        "entities",
        'a JSON array of 2-6 {"name": string, "type": string, "sameAs": string} '
        "objects: the companies, products, people, and models the video is "
        "actually about. type is one of Organization, Person, Product, "
        "SoftwareApplication. sameAs is a Wikipedia or Wikidata URL for "
        "that entity -- omit sameAs entirely unless you are confident the "
        "page exists; a wrong URL is worse than none",
    ),
)

INTERNAL_LINK_INSTRUCTIONS = (
    "Internal links: related_articles below lists articles already "
    "published on this site. When one is genuinely relevant to something "
    "you're saying in the body, link to it inline as "
    "[natural anchor text](/articles/<slug>), with anchor text that "
    "describes the linked topic in your own words -- never the headline "
    'verbatim, never "here" or "read more". Use at most 3 such links, in '
    "different paragraphs, never the same slug twice, never inside a "
    "subheading. Only ever link to a slug listed in related_articles -- "
    "never invent or guess a URL. Do not link to /categories/ or /tags/ "
    "pages. If nothing is genuinely relevant, add no links: a forced link "
    "is worse than no link."
)


def build_json_instructions(site_profile: SiteProfile, related: list[dict] | None = None) -> str:
    categories = ", ".join(f'"{c}"' for c in site_profile.categories)
    extra_lines = "".join(
        f'  "{key}": {text}\n'
        for key, text in EXTRA_FIELD_INSTRUCTIONS
        if key in site_profile.extra_fields
    )
    instructions = (
        "Respond with ONLY a JSON object (no markdown fences, no preamble, "
        "no commentary before or after) with exactly these keys:\n"
        '  "title": a concise, specific headline, plain text, not clickbait\n'
        '  "summary": a 1-2 sentence standfirst\n'
        f'  "body": the full article body as {site_profile.body_style_hint}\n'
        f'  "category": exactly one of: {categories}\n'
        '  "tags": a JSON array of 3-6 lowercase-hyphenated topic tags\n'
        f"{extra_lines}\n"
        "Write in English regardless of the source's original language. "
        "Do not invent facts not present in the source."
    )
    if related:
        instructions += (
            f"\n\n{INTERNAL_LINK_INSTRUCTIONS}\n\n"
            f"related_articles: {json.dumps(related, ensure_ascii=False)}"
        )
    return instructions


def extract_json(raw_text: str) -> dict:
    """Best-effort extraction of a JSON object from a model response that
    may be wrapped in markdown code fences or have stray preamble/trailing
    commentary around it, despite being asked not to."""
    text = raw_text.strip()

    fence_match = _JSON_FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    return json.loads(text)


def parse_article(raw_text: str, site_profile: SiteProfile, video_id: str) -> ArticleContent:
    """The single validation point for provider JSON output. Raises
    SummaryError for missing/empty required fields or malformed tags.
    Falls back to category="general" (present in every site's taxonomy)
    with a logged warning if the model returns a category outside
    site_profile.categories, rather than retrying or crashing the video."""
    try:
        data = extract_json(raw_text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise SummaryError(
            f"Could not parse JSON article response for video {video_id}: {exc}. "
            f"Raw response: {raw_text[:500]}"
        ) from exc

    if not isinstance(data, dict):
        raise SummaryError(
            f"Article response for video {video_id} was not a JSON object: {raw_text[:500]}"
        )

    missing_or_empty = [key for key in REQUIRED_STRING_KEYS if not str(data.get(key, "")).strip()]
    if missing_or_empty:
        raise SummaryError(
            f"Article response for video {video_id} is missing required field(s) "
            f"{missing_or_empty}: {raw_text[:500]}"
        )

    tags_raw = data.get("tags")
    if not isinstance(tags_raw, list) or not tags_raw:
        raise SummaryError(
            f"Article response for video {video_id} has missing/malformed 'tags': {raw_text[:500]}"
        )
    tags = [str(t).strip().lower().replace(" ", "-") for t in tags_raw if str(t).strip()]
    if not tags:
        raise SummaryError(f"Article response for video {video_id} produced no usable tags")

    category = str(data["category"]).strip().lower()
    if category not in site_profile.categories:
        logger.warning(
            "Video %s: model returned invalid category %r for site %s (valid: %s) "
            "-- falling back to 'general'",
            video_id,
            category,
            site_profile.key,
            site_profile.categories,
        )
        category = "general"

    # Optional fields are lenient: a malformed value is dropped, never a
    # reason to fail the whole video -- the site renders fine without them.
    extras = site_profile.extra_fields
    return ArticleContent(
        title=str(data["title"]).strip(),
        summary=str(data["summary"]).strip(),
        body=str(data["body"]).strip(),
        category=category,
        tags=tags,
        seo_title=_clean_line(data.get("seoTitle"), 70) if "seoTitle" in extras else "",
        meta_description=(
            _clean_line(data.get("metaDescription"), 180) if "metaDescription" in extras else ""
        ),
        key_takeaways=clean_takeaways(data.get("keyTakeaways")) if "keyTakeaways" in extras else [],
        faq=clean_faq(data.get("faq")) if "faq" in extras else [],
        entities=clean_entities(data.get("entities")) if "entities" in extras else [],
    )


def _clean_line(value, max_len: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:max_len].strip()


def clean_takeaways(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = " ".join(re.sub(r"[*_`#]", "", item).split()).lstrip("-•* ").strip()
        # Too short to be a self-contained claim.
        if len(text) < 25:
            continue
        out.append(text[:200])
    return out[:5]


def clean_faq(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, dict):
            continue
        question = _clean_line(item.get("question"), 200)
        answer = _clean_line(item.get("answer"), 600)
        if not question or not answer:
            continue
        if not question.endswith("?"):
            question = f"{question}?"
        out.append({"question": question, "answer": answer})
    return out[:4]


SCHEMA_ENTITY_TYPES = {"Organization", "Person", "Product", "SoftwareApplication", "Thing"}

# Only Wikipedia/Wikidata: a fabricated sameAs URL in schema is an error a
# validator will flag, so anything else is dropped.
_SAME_AS_RE = re.compile(
    r"^https://([a-z]{2}\.)?wikipedia\.org/wiki/\S+$|^https://www\.wikidata\.org/wiki/Q\d+$"
)


def clean_entities(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    out = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _clean_line(item.get("name"), 120)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())

        entity_type = item.get("type")
        entity = {"name": name, "type": entity_type if entity_type in SCHEMA_ENTITY_TYPES else "Thing"}
        same_as = str(item.get("sameAs") or "").strip()
        if _SAME_AS_RE.match(same_as):
            entity["sameAs"] = same_as
        out.append(entity)
    return out[:6]
