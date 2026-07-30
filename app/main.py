"""CLI entrypoint: fetches new videos from the configured target site's
playlist, generates an article for each with the configured provider,
publishes into that site's repo, and persists which videos have been
processed.

Usage: python -m app.main [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import sys

from app.config import Config, ConfigError, load_config
from app.publish.site_publisher import PublishError, SitePublisher
from app.state import StateFileError, StateStore
from app.summarize import SummaryError, get_provider
from app.summarize.base import SummaryProvider
from app.youtube import VideoMetadata, YouTubeApiError, fetch_playlist_videos

logger = logging.getLogger("app")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize and publish new YouTube playlist videos as site articles."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Generate articles and log what would be published, but never "
            "clone/push to the site repo or save processed-video state."
        ),
    )
    return parser.parse_args(argv)


def _process_videos(
    videos: list[VideoMetadata],
    provider: SummaryProvider,
    config: Config,
    state: StateStore,
    publisher: SitePublisher | None,
    *,
    dry_run: bool,
) -> bool:
    """Processes each video independently: a failure never aborts the rest
    of the batch and never marks that video processed (so it's retried
    next run). Returns whether anything was newly marked processed."""
    processed_any = False

    for video in videos:
        if video.is_unavailable:
            logger.warning("Skipping unavailable video %s (%s)", video.video_id, video.title)
            if not dry_run:
                state.mark_processed(video.video_id, video.title, status="skipped_unavailable")
                processed_any = True
            continue

        try:
            article = provider.generate_article(video, config.site_profile)

            if dry_run:
                logger.info(
                    "[dry-run] Would publish video %s (%s) [category=%s tags=%s]\n%s",
                    video.video_id,
                    video.title,
                    article.category,
                    article.tags,
                    article.summary,
                )
                continue

            assert publisher is not None
            slug = publisher.publish(video, article)
            state.mark_processed(video.video_id, video.title)
            processed_any = True
            logger.info(
                "Published video %s (%s) as %s/%s",
                video.video_id,
                video.title,
                config.target_site,
                slug,
            )

        except (SummaryError, PublishError) as exc:
            logger.error("Failed to process video %s (%s): %s", video.video_id, video.title, exc)
        except Exception:
            logger.exception(
                "Unexpected error processing video %s (%s)", video.video_id, video.title
            )

    return processed_any


def run(config: Config, *, dry_run: bool) -> int:
    state = StateStore(config.state_file_path)
    state.load()

    videos = fetch_playlist_videos(config.youtube_api_key, config.site_profile.playlist_id)
    logger.info(
        "Fetched %d video(s) from playlist %s (target site: %s)",
        len(videos),
        config.site_profile.playlist_id,
        config.target_site,
    )

    pending = [v for v in videos if not state.is_processed(v.video_id)]
    to_process = pending[: config.max_videos_per_run]
    logger.info(
        "%d video(s) not yet processed; processing up to %d this run",
        len(pending),
        config.max_videos_per_run,
    )

    provider = get_provider(config)

    if dry_run:
        # Dry runs never clone/push/save state -- see app/publish and
        # app/state.py. Processed entirely without a SitePublisher.
        _process_videos(to_process, provider, config, state, publisher=None, dry_run=True)
        return 0

    try:
        with SitePublisher(config.site_profile, config.site_repo_pat) as publisher:
            processed_any = _process_videos(
                to_process, provider, config, state, publisher, dry_run=False
            )
    except PublishError as exc:
        # The clone itself failed -- fatal for the whole run, since nothing
        # could have been published. Per-video PublishErrors are caught
        # inside _process_videos and never reach here.
        logger.error("Fatal error: %s", exc)
        return 1

    if processed_any:
        state.save()

    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    args = parse_args(argv)

    try:
        config = load_config(dry_run=args.dry_run)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 1

    try:
        return run(config, dry_run=args.dry_run)
    except (YouTubeApiError, StateFileError) as exc:
        logger.error("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
