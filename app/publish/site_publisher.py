"""Publishes generated articles + thumbnails into a site repo, via a local
shallow clone pushed with a cross-repo Personal Access Token.

Used as a context manager so the clone is made once per run (reused
across every video processed in that run) and always cleaned up. Staging
and pushing are two separate steps, specifically so a run that processes
several videos for the same site results in exactly ONE push (and
therefore one Vercel deploy) instead of one push per video:

    with SitePublisher(site_profile, pat) as publisher:
        for video, article in ...:
            slug = publisher.stage(video, article)
        publisher.push_all()
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
    """Raised when staging a video's article fails, or when pushing the
    batch of staged articles to the site repo fails."""


class SitePublisher:
    def __init__(self, site_profile: SiteProfile, pat: str, *, session=None):
        self._site_profile = site_profile
        self._pat = pat
        self._session = session
        self._clone_dir: str | None = None
        self._staged_paths: list[str] = []
        self._staged_entries: list[tuple[str, str]] = []  # (video_id, title)

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

    def stage(self, video: VideoMetadata, article: ArticleContent) -> str:
        """Writes the article JSON + thumbnail image into the local clone.
        Does NOT commit or push -- call push_all() once after staging
        every video for this run. Returns the slug that will be used once
        pushed. Raises PublishError on thumbnail download failure; this is
        isolated per video exactly like every other per-video error in
        this app -- it does not affect any other video staged this run."""
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

        self._staged_paths.extend([article_rel_path, image_rel_path])
        self._staged_entries.append((video.video_id, article.title))

        return slug

    def push_all(self) -> int:
        """Commits and pushes every file staged so far via stage(), as ONE
        commit -- so a run that stages N videos results in exactly one
        push (and one Vercel deploy) instead of N. Returns the number of
        videos included (0 if nothing was staged, in which case no git
        operations happen at all -- safe to call unconditionally). Raises
        PublishError if the push fails after retries; nothing was left
        committed in that case, so the caller must not mark any staged
        video as processed -- they'll be regenerated and retried next
        run."""
        if self._clone_dir is None:
            raise RuntimeError("SitePublisher must be used as a context manager")
        if not self._staged_paths:
            return 0

        count = len(self._staged_entries)
        try:
            commit_and_push_with_retry(
                repo_path=self._clone_dir,
                branch=self._site_profile.default_branch,
                paths_to_add=self._staged_paths,
                commit_message=self._commit_message(),
            )
        except GitOpsError as exc:
            raise PublishError(
                f"Failed to push batch of {count} article(s) to "
                f"{self._site_profile.repo_name}: {exc}"
            ) from exc

        self._staged_paths = []
        self._staged_entries = []
        return count

    def _commit_message(self) -> str:
        """N == 1 keeps the exact single-video message used before
        batching existed, so the common case leaves this tool's git
        history unchanged in style. N > 1 uses a subject + bullet-list
        body so `git log --oneline` still shows a short summary while the
        full message records exactly which videos were included.
        Deliberately plain-text (not the site's own "Daily digest" emoji
        style) so this tool's commits stay visually distinct from the
        site's own pipeline commits."""
        if len(self._staged_entries) == 1:
            video_id, title = self._staged_entries[0]
            return f"Add article from YouTube video {video_id}: {title}"

        subject = f"Add {len(self._staged_entries)} articles from YouTube videos"
        body = "\n".join(f"- {video_id}: {title}" for video_id, title in self._staged_entries)
        return f"{subject}\n\n{body}"

    def _unique_slug(self, publish_date: datetime, title: str) -> str:
        base_slug = f"{publish_date:%Y-%m-%d}-{slugify(title)}"
        articles_dir = os.path.join(self._clone_dir, "content", "articles")
        slug = base_slug
        suffix = 2
        while os.path.exists(os.path.join(articles_dir, f"{slug}.json")):
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        return slug
