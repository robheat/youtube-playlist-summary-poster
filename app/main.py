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
) -> tuple[bool, list[VideoMetadata]]:
    """Processes each video independently: a failure never aborts the rest
    of the batch. Unavailable videos are marked processed immediately (no
    git involved). Every other video whose article generates successfully
    is STAGED into the publisher's local clone -- files written to disk,
    nothing committed or pushed yet. The caller must call
    publisher.push_all() once after this returns and call
    state.mark_processed() for the returned videos ONLY if that push
    succeeds; staging alone must never mark a video processed. Returns
    (processed_any_immediately, staged_videos)."""
    processed_any = False
    staged_videos: list[VideoMetadata] = []

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
            slug = publisher.stage(video, article)
            staged_videos.append(video)
            logger.info(
                "Staged video %s (%s) as %s/%s (pushed with the rest of this run's batch)",
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

    return processed_any, staged_videos


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
            processed_any, staged_videos = _process_videos(
                to_process, provider, config, state, publisher, dry_run=False
            )

            if staged_videos:
                try:
                    pushed_count = publisher.push_all()
                except PublishError as exc:
                    # Non-fatal: article generation for these videos already
                    # happened (the expensive part), and nothing was actually
                    # published -- commit_and_push_with_retry discards the
                    # failed local commit. They simply stay unmarked and get
                    # regenerated and retried next run, exactly like any
                    # other per-video PublishError above.
                    logger.error(
                        "Failed to push batch of %d video(s) to %s -- all will be "
                        "retried next run: %s",
                        len(staged_videos),
                        config.target_site,
                        exc,
                    )
                else:
                    for video in staged_videos:
                        state.mark_processed(video.video_id, video.title)
                    processed_any = True
                    logger.info(
                        "Pushed %d video(s) to %s in a single commit",
                        pushed_count,
                        config.target_site,
                    )
    except PublishError as exc:
        # The clone itself failed -- fatal for the whole run, since nothing
        # could have been staged or published. Per-video staging errors and
        # the batch-push error above are both handled inside the `with`
        # block and never reach here.
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
