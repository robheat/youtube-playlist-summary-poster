"""Publishes a generated article + thumbnail into a site repo, via a local
shallow clone pushed with a cross-repo Personal Access Token.

Used as a context manager so the clone is made once per run (reused
across every video processed in that run) and always cleaned up:

    with SitePublisher(site_profile, pat) as publisher:
        slug = publisher.publish(video, article)
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone

from app.config import SiteProfile
from app.publish.git_ops import (
    GitOpsError,
    build_authenticated_url,
    clone_repo,
    commit_and_push_with_retry,
)
from app.publish.image_dims import jpeg_size
from app.publish.images import ImageDownloadError, download_thumbnail
from app.publish.slugify import slugify
from app.summarize.base import ArticleContent
from app.youtube import VideoMetadata


class PublishError(RuntimeError):
    """Raised when publishing a video's article to the site repo fails."""


class SitePublisher:
    def __init__(self, site_profile: SiteProfile, pat: str, *, session=None):
        self._site_profile = site_profile
        self._pat = pat
        self._session = session
        self._clone_dir: str | None = None

    def __enter__(self) -> "SitePublisher":
        self._clone_dir = tempfile.mkdtemp(prefix="site-publish-")
        try:
            url = build_authenticated_url(
                self._site_profile.repo_owner, self._site_profile.repo_name, self._pat
            )
            clone_repo(url=url, branch=self._site_profile.default_branch, dest=self._clone_dir)
        except GitOpsError as exc:
            self._cleanup()
            raise PublishError(f"Failed to clone {self._site_profile.repo_name}: {exc}") from exc
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._cleanup()

    def _cleanup(self) -> None:
        if self._clone_dir and os.path.isdir(self._clone_dir):
            shutil.rmtree(self._clone_dir, ignore_errors=True)
        self._clone_dir = None

    def publish(self, video: VideoMetadata, article: ArticleContent) -> str:
        """Writes the article JSON + thumbnail image into the clone and
        pushes them as one commit. Returns the published slug. Raises
        PublishError on failure."""
        if self._clone_dir is None:
            raise RuntimeError("SitePublisher must be used as a context manager")

        publish_date = datetime.now(timezone.utc)
        slug = self._unique_slug(publish_date, article.title)

        try:
            thumbnail_bytes = download_thumbnail(video.thumbnail_url, session=self._session)
        except ImageDownloadError as exc:
            raise PublishError(str(exc)) from exc

        dims = jpeg_size(thumbnail_bytes)

        article_rel_path = f"content/articles/{slug}.json"
        image_rel_path = f"public/images/articles/{slug}.jpg"
        article_path = os.path.join(self._clone_dir, "content", "articles", f"{slug}.json")
        image_path = os.path.join(self._clone_dir, "public", "images", "articles", f"{slug}.jpg")

        payload = {
            "slug": slug,
            "title": article.title,
            "summary": article.summary,
            "body": article.body,
            "sourceUrl": video.watch_url,
            "sourceName": video.channel_title or self._site_profile.default_source_name,
            "category": article.category,
            "tags": article.tags,
            "publishedAt": publish_date.isoformat(),
            "imageUrl": f"/images/articles/{slug}.jpg",
            "youtubeVideoId": video.video_id,
        }
        if dims is not None:
            payload["imageWidth"], payload["imageHeight"] = dims

        os.makedirs(os.path.dirname(article_path), exist_ok=True)
        os.makedirs(os.path.dirname(image_path), exist_ok=True)
        with open(article_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        with open(image_path, "wb") as f:
            f.write(thumbnail_bytes)

        try:
            commit_and_push_with_retry(
                repo_path=self._clone_dir,
                branch=self._site_profile.default_branch,
                paths_to_add=[article_rel_path, image_rel_path],
                commit_message=f"Add article from YouTube video {video.video_id}: {article.title}",
            )
        except GitOpsError as exc:
            raise PublishError(
                f"Failed to publish video {video.video_id} to "
                f"{self._site_profile.repo_name}: {exc}"
            ) from exc

        return slug

    def _unique_slug(self, publish_date: datetime, title: str) -> str:
        base_slug = f"{publish_date:%Y-%m-%d}-{slugify(title)}"
        articles_dir = os.path.join(self._clone_dir, "content", "articles")
        slug = base_slug
        suffix = 2
        while os.path.exists(os.path.join(articles_dir, f"{slug}.json")):
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        return slug
