"""Tests for app.main's orchestration logic in run() -- the highest-value
test file in the suite. These catch the correctness properties the design
depends on: a failed video never blocks the rest of the batch, dry-run
never has side effects, and unavailable videos are auto-skipped.
"""
from __future__ import annotations

from unittest.mock import patch

from app.config import Config
from app.main import parse_args, run
from app.publisher import PublishError
from app.state import StateStore
from app.summarize.base import SummaryError
from app.youtube import VideoMetadata


def _make_config(tmp_path, **overrides) -> Config:
    defaults = dict(
        youtube_api_key="yt-key",
        playlist_id="PL123",
        summary_provider="gemini",
        gemini_api_key="gemini-key",
        gemini_model="gemini-2.5-flash",
        venice_api_key=None,
        venice_model=None,
        webshare_proxy_username=None,
        webshare_proxy_password=None,
        website_api_url="https://example.com/api/videos",
        website_api_key="website-key",
        max_videos_per_run=5,
        state_file_path=str(tmp_path / "processed_videos.json"),
    )
    defaults.update(overrides)
    return Config(**defaults)


def _make_video(video_id, title="Some Title") -> VideoMetadata:
    return VideoMetadata(
        video_id=video_id,
        title=title,
        description="desc",
        published_at="2026-01-01T00:00:00Z",
        added_to_playlist_at="2026-01-01T00:00:00Z",
        thumbnail_url="https://img.example.com/thumb.jpg",
        channel_title="Channel",
        watch_url=f"https://www.youtube.com/watch?v={video_id}",
        embed_url=f"https://www.youtube.com/embed/{video_id}",
    )


class FakeProvider:
    def __init__(self, summaries=None, raises_for=None):
        self._summaries = summaries or {}
        self._raises_for = raises_for or {}
        self.calls = []

    def summarize(self, video):
        self.calls.append(video.video_id)
        if video.video_id in self._raises_for:
            raise self._raises_for[video.video_id]
        return self._summaries.get(video.video_id, "A summary.")


def test_parse_args_dry_run_flag():
    assert parse_args(["--dry-run"]).dry_run is True
    assert parse_args([]).dry_run is False


def test_video_failure_does_not_stop_batch_or_mark_processed(tmp_path):
    config = _make_config(tmp_path)
    videos = [_make_video("good1"), _make_video("bad"), _make_video("good2")]
    provider = FakeProvider(raises_for={"bad": SummaryError("boom")})
    published = []

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch(
            "app.main.publish_video",
            side_effect=lambda api_url, api_key, video, summary: published.append(video.video_id),
        ),
    ):
        exit_code = run(config, dry_run=False)

    assert exit_code == 0
    assert provider.calls == ["good1", "bad", "good2"]
    assert published == ["good1", "good2"]

    state = StateStore(config.state_file_path)
    state.load()
    assert state.is_processed("good1")
    assert state.is_processed("good2")
    assert not state.is_processed("bad")


def test_publish_failure_does_not_mark_processed(tmp_path):
    config = _make_config(tmp_path)
    videos = [_make_video("vid1")]
    provider = FakeProvider()

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.publish_video", side_effect=PublishError("website down")),
    ):
        exit_code = run(config, dry_run=False)

    assert exit_code == 0
    state = StateStore(config.state_file_path)
    state.load()
    assert not state.is_processed("vid1")


def test_max_videos_per_run_caps_batch(tmp_path):
    config = _make_config(tmp_path, max_videos_per_run=2)
    videos = [_make_video(f"vid{i}") for i in range(5)]
    provider = FakeProvider()

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.publish_video"),
    ):
        run(config, dry_run=False)

    assert provider.calls == ["vid0", "vid1"]


def test_dry_run_never_publishes_or_saves_state(tmp_path):
    config = _make_config(tmp_path)
    videos = [_make_video("vid1")]
    provider = FakeProvider()

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.publish_video") as fake_publish,
    ):
        run(config, dry_run=True)

    fake_publish.assert_not_called()
    assert not (tmp_path / "processed_videos.json").exists()


def test_dry_run_skips_unavailable_video_without_marking_processed(tmp_path):
    config = _make_config(tmp_path)
    videos = [_make_video("private1", title="Private video")]
    provider = FakeProvider()

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.publish_video"),
    ):
        run(config, dry_run=True)

    assert provider.calls == []
    assert not (tmp_path / "processed_videos.json").exists()


def test_unavailable_video_skipped_without_calling_provider(tmp_path):
    config = _make_config(tmp_path)
    videos = [_make_video("private1", title="Private video"), _make_video("good1")]
    provider = FakeProvider()

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.publish_video"),
    ):
        run(config, dry_run=False)

    assert provider.calls == ["good1"]
    state = StateStore(config.state_file_path)
    state.load()
    assert state.is_processed("private1")
    assert state.is_processed("good1")


def test_already_processed_videos_are_skipped(tmp_path):
    config = _make_config(tmp_path)
    seed = StateStore(config.state_file_path)
    seed.load()
    seed.mark_processed("vid1", "Already done")
    seed.save()

    videos = [_make_video("vid1"), _make_video("vid2")]
    provider = FakeProvider()

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.publish_video"),
    ):
        run(config, dry_run=False)

    assert provider.calls == ["vid2"]


def test_unexpected_exception_from_provider_does_not_crash_batch(tmp_path):
    config = _make_config(tmp_path)
    videos = [_make_video("vid1"), _make_video("vid2")]
    provider = FakeProvider(raises_for={"vid1": ValueError("totally unexpected")})

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.publish_video"),
    ):
        exit_code = run(config, dry_run=False)

    assert exit_code == 0
    assert provider.calls == ["vid1", "vid2"]
    state = StateStore(config.state_file_path)
    state.load()
    assert not state.is_processed("vid1")
    assert state.is_processed("vid2")
