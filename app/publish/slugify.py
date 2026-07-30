"""ASCII-forced port of ainformed-dev's lib/utils.ts slugify():

    text.toLowerCase().replace(/[^\\w\\s-]/g, "").replace(/\\s+/g, "-").replace(/-+/g, "-").trim()

JavaScript's bare \\w is ASCII-only ([A-Za-z0-9_]), but Python's \\w on a
str pattern is Unicode-aware by default -- a naive port would keep
accented/non-Latin characters the TS version strips, producing different
slugs than the site's own pipeline would for the same title.
"""
from __future__ import annotations

import re


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.ASCII)
    text = re.sub(r"\s+", "-", text, flags=re.ASCII)
    text = re.sub(r"-+", "-", text)
    return text.strip()
