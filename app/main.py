"""CLI entrypoint: fetches new playlist videos, summarizes each with the
configured provider, publishes to the destination website, and persists
which videos have been processed.

Usage: python -m app.main [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import sys

from app.config import Config, ConfigError, load_config
from app.publisher import PublishError, publish_video
from app.state import StateFileError, StateStore
from app.summarize import SummaryError, get_provider
from app.youtube import YouTubeApiError, fetch_playlist_videos

logger = logging.getLogger("app")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize and publish new YouTube playlist videos."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Summarize videos and log what would be published, but never "
            "publish to the website or save processed-video state."
        ),
    )
    return parser.parse_args(argv)


def run(config: Config, *, dry_run: bool) -> int:
    state = StateStore(config.state_file_path)
    state.load()

    videos = fetch_playlist_videos(config.youtube_api_key, config.playlist_id)
    logger.info("Fetched %d video(s) from playlist %s", len(videos), config.playlist_id)

    pending = [v for v in videos if not state.is_processed(v.video_id)]
    to_process = pending[: config.max_videos_per_run]
    logger.info(
        "%d video(s) not yet processed; processing up to %d this run",
        len(pending),
        config.max_videos_per_run,
    )

    provider = get_provider(config)
    processed_any = False

    for video in to_process:
        if video.is_unavailable:
            logger.warning("Skipping unavailable video %s (%s)", video.video_id, video.title)
            if not dry_run:
                state.mark_processed(video.video_id, video.title, status="skipped_unavailable")
                processed_any = True
            continue

        try:
            summary = provider.summarize(video)

            if dry_run:
                logger.info(
                    "[dry-run] Would publish video %s (%s):\n%s",
                    video.video_id,
                    video.title,
                    summary,
                )
                continue

            publish_video(config.website_api_url, config.website_api_key, video, summary)
            state.mark_processed(video.video_id, video.title)
            processed_any = True
            logger.info("Published video %s (%s)", video.video_id, video.title)

        except (SummaryError, PublishError) as exc:
            # Expected failure modes: not marked processed, so this video
            # is retried on the next run. Never aborts the rest of the batch.
            logger.error("Failed to process video %s (%s): %s", video.video_id, video.title, exc)
        except Exception:
            # Defense in depth: an unanticipated error from inside a
            # provider or the publisher still must not take down the batch.
            logger.exception(
                "Unexpected error processing video %s (%s)", video.video_id, video.title
            )

    # Dry runs must never persist state -- see app/state.py and README.md.
    if not dry_run and processed_any:
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
        # Fatal, whole-run failures: bad config that slipped past
        # load_config, can't reach the playlist at all, or a corrupt state
        # file. Per-video failures are handled inside run() and never
        # reach here.
        logger.error("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
