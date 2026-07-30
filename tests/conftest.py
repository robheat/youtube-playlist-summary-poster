import pytest

from app.youtube import VideoMetadata


@pytest.fixture
def sample_video() -> VideoMetadata:
    return VideoMetadata(
        video_id="abc123",
        title="Sample Video Title",
        description="Sample description.",
        published_at="2026-01-01T00:00:00Z",
        added_to_playlist_at="2026-01-02T00:00:00Z",
        thumbnail_url="https://i.ytimg.com/vi/abc123/hqdefault.jpg",
        channel_title="Sample Channel",
        watch_url="https://www.youtube.com/watch?v=abc123",
        embed_url="https://www.youtube.com/embed/abc123",
    )
