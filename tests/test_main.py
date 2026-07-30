"""Tests for app.main's orchestration logic in run() -- the highest-value
test file in the suite. These catch the correctness properties the design
depends on: a failed video never blocks the rest of the batch, a clone
failure is fatal to the whole run (nothing could have been published),
dry-run never has side effects, and unavailable videos are auto-skipped.
"""
from __future__ import annotations

from unittest.mock import patch

from app.config import Config
from app.main import parse_args, run
from app.publish.site_publisher import PublishError
from app.state import StateStore
from app.summarize.base import ArticleContent, SummaryError
from app.youtube import VideoMetadata


def _make_config(tmp_path, site_profile, **overrides) -> Config:
    defaults = dict(
        youtube_api_key="yt-key",
        target_site=site_profile.key,
        site_profile=site_profile,
        summary_provider="gemini",
        gemini_api_key="gemini-key",
        gemini_model="gemini-2.5-flash",
        venice_api_key=None,
        venice_model="mistral-small-3-2-24b-instruct",
        webshare_proxy_username=None,
        webshare_proxy_password=None,
        site_repo_pat="fake-pat",
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


def _make_article() -> ArticleContent:
    return ArticleContent(
        title="Title", summary="Summary", body="Body", category="general", tags=["tag"]
    )


class FakeProvider:
    def __init__(self, raises_for=None):
        self._raises_for = raises_for or {}
        self.calls = []

    def generate_article(self, video, site_profile):
        self.calls.append(video.video_id)
        if video.video_id in self._raises_for:
            raise self._raises_for[video.video_id]
        return _make_article()


class FakePublisher:
    def __init__(self, *args, raise_on_enter=None, raise_on_publish_for=None, **kwargs):
        self._raise_on_enter = raise_on_enter
        self._raise_on_publish_for = raise_on_publish_for or {}
        self.published = []

    def __enter__(self):
        if self._raise_on_enter:
            raise self._raise_on_enter
        return self

    def __exit__(self, *args):
        return False

    def publish(self, video, article):
        if video.video_id in self._raise_on_publish_for:
            raise self._raise_on_publish_for[video.video_id]
        self.published.append(video.video_id)
        return f"slug-{video.video_id}"


def test_parse_args_dry_run_flag():
    assert parse_args(["--dry-run"]).dry_run is True
    assert parse_args([]).dry_run is False


def test_video_failure_does_not_stop_batch_or_mark_processed(tmp_path, sample_site_profile):
    config = _make_config(tmp_path, sample_site_profile)
    videos = [_make_video("good1"), _make_video("bad"), _make_video("good2")]
    provider = FakeProvider(raises_for={"bad": SummaryError("boom")})
    fake_publisher = FakePublisher()

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.SitePublisher", return_value=fake_publisher),
    ):
        exit_code = run(config, dry_run=False)

    assert exit_code == 0
    assert provider.calls == ["good1", "bad", "good2"]
    assert fake_publisher.published == ["good1", "good2"]

    state = StateStore(config.state_file_path)
    state.load()
    assert state.is_processed("good1")
    assert state.is_processed("good2")
    assert not state.is_processed("bad")


def test_publish_failure_does_not_mark_processed(tmp_path, sample_site_profile):
    config = _make_config(tmp_path, sample_site_profile)
    videos = [_make_video("vid1")]
    provider = FakeProvider()
    fake_publisher = FakePublisher(raise_on_publish_for={"vid1": PublishError("push failed")})

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.SitePublisher", return_value=fake_publisher),
    ):
        exit_code = run(config, dry_run=False)

    assert exit_code == 0
    state = StateStore(config.state_file_path)
    state.load()
    assert not state.is_processed("vid1")


def test_clone_failure_is_fatal_to_whole_run(tmp_path, sample_site_profile):
    config = _make_config(tmp_path, sample_site_profile)
    videos = [_make_video("vid1")]
    provider = FakeProvider()
    fake_publisher = FakePublisher(raise_on_enter=PublishError("clone failed"))

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.SitePublisher", return_value=fake_publisher),
    ):
        exit_code = run(config, dry_run=False)

    assert exit_code == 1
    assert provider.calls == []  # never even got to processing videos
    state = StateStore(config.state_file_path)
    state.load()
    assert not state.is_processed("vid1")


def test_max_videos_per_run_caps_batch(tmp_path, sample_site_profile):
    config = _make_config(tmp_path, sample_site_profile, max_videos_per_run=2)
    videos = [_make_video(f"vid{i}") for i in range(5)]
    provider = FakeProvider()
    fake_publisher = FakePublisher()

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.SitePublisher", return_value=fake_publisher),
    ):
        run(config, dry_run=False)

    assert provider.calls == ["vid0", "vid1"]


def test_dry_run_never_publishes_or_saves_state(tmp_path, sample_site_profile):
    config = _make_config(tmp_path, sample_site_profile)
    videos = [_make_video("vid1")]
    provider = FakeProvider()

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.SitePublisher") as fake_publisher_cls,
    ):
        run(config, dry_run=True)

    fake_publisher_cls.assert_not_called()
    assert not (tmp_path / "processed_videos.json").exists()


def test_dry_run_skips_unavailable_video_without_marking_processed(tmp_path, sample_site_profile):
    config = _make_config(tmp_path, sample_site_profile)
    videos = [_make_video("private1", title="Private video")]
    provider = FakeProvider()

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.SitePublisher") as fake_publisher_cls,
    ):
        run(config, dry_run=True)

    assert provider.calls == []
    fake_publisher_cls.assert_not_called()
    assert not (tmp_path / "processed_videos.json").exists()


def test_unavailable_video_skipped_without_calling_provider(tmp_path, sample_site_profile):
    config = _make_config(tmp_path, sample_site_profile)
    videos = [_make_video("private1", title="Private video"), _make_video("good1")]
    provider = FakeProvider()
    fake_publisher = FakePublisher()

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.SitePublisher", return_value=fake_publisher),
    ):
        run(config, dry_run=False)

    assert provider.calls == ["good1"]
    state = StateStore(config.state_file_path)
    state.load()
    assert state.is_processed("private1")
    assert state.is_processed("good1")


def test_already_processed_videos_are_skipped(tmp_path, sample_site_profile):
    config = _make_config(tmp_path, sample_site_profile)
    seed = StateStore(config.state_file_path)
    seed.load()
    seed.mark_processed("vid1", "Already done")
    seed.save()

    videos = [_make_video("vid1"), _make_video("vid2")]
    provider = FakeProvider()
    fake_publisher = FakePublisher()

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.SitePublisher", return_value=fake_publisher),
    ):
        run(config, dry_run=False)

    assert provider.calls == ["vid2"]


def test_unexpected_exception_from_provider_does_not_crash_batch(tmp_path, sample_site_profile):
    config = _make_config(tmp_path, sample_site_profile)
    videos = [_make_video("vid1"), _make_video("vid2")]
    provider = FakeProvider(raises_for={"vid1": ValueError("totally unexpected")})
    fake_publisher = FakePublisher()

    with (
        patch("app.main.fetch_playlist_videos", return_value=videos),
        patch("app.main.get_provider", return_value=provider),
        patch("app.main.SitePublisher", return_value=fake_publisher),
    ):
        exit_code = run(config, dry_run=False)

    assert exit_code == 0
    assert provider.calls == ["vid1", "vid2"]
    state = StateStore(config.state_file_path)
    state.load()
    assert not state.is_processed("vid1")
    assert state.is_processed("vid2")
