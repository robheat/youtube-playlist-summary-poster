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


def build_json_instructions(site_profile: SiteProfile) -> str:
    categories = ", ".join(f'"{c}"' for c in site_profile.categories)
    return (
        "Respond with ONLY a JSON object (no markdown fences, no preamble, "
        "no commentary before or after) with exactly these keys:\n"
        '  "title": a concise, specific headline, plain text, not clickbait\n'
        '  "summary": a 1-2 sentence standfirst\n'
        f'  "body": the full article body as {site_profile.body_style_hint}\n'
        f'  "category": exactly one of: {categories}\n'
        '  "tags": a JSON array of 3-6 lowercase-hyphenated topic tags\n\n'
        "Write in English regardless of the source's original language. "
        "Do not invent facts not present in the source."
    )


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

    return ArticleContent(
        title=str(data["title"]).strip(),
        summary=str(data["summary"]).strip(),
        body=str(data["body"]).strip(),
        category=category,
        tags=tags,
    )
