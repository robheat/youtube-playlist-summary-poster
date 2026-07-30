"""Downloads a video's thumbnail image for committing into a site repo."""
from __future__ import annotations

import requests


class ImageDownloadError(RuntimeError):
    """Raised when a thumbnail image can't be downloaded."""


def download_thumbnail(
    url: str, *, session: requests.Session | None = None, timeout: int = 30
) -> bytes:
    http = session if session is not None else requests
    try:
        response = http.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise ImageDownloadError(f"Failed to download thumbnail {url}: {exc}") from exc

    if response.status_code != 200:
        raise ImageDownloadError(
            f"Failed to download thumbnail {url}: status {response.status_code}"
        )

    return response.content
