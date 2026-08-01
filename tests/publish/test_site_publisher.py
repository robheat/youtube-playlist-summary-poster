"""Tests for app.publish.site_publisher.SitePublisher.

git_ops itself is mocked here (it's separately proven against a real repo
in test_git_ops.py) -- these tests focus on slug-bumping, file-writing,
and the stage()/push_all() split that batches every video processed in a
run into a single commit (see push_all()'s docstring for why).
"""
from __future__ import annotations

import dataclasses
import json
import os
from unittest.mock import patch

import pytest

from app.publish.git_ops import GitOpsError
from app.publish.images import ImageDownloadError
from app.publish.site_publisher import PublishError, SitePublisher
from app.summarize.base import ArticleContent

# Reuse the same minimal hand-built JPEG (200x100) from test_image_dims.py
MINIMAL_JPEG_200x100 = bytes(
    [
        0xFF, 0xD8,
        0xFF, 0xC0,
        0x00, 0x11,
        0x08,
        0x00, 0x64,
        0x00, 0xC8,
        0x03,
        0x01, 0x22, 0x00,
        0x02, 0x11, 0x01,
        0x03, 0x11, 0x01,
    ]
)

SAMPLE_ARTICLE = ArticleContent(
    title="Bitcoin Nears $85K Resistance",
    summary="A short standfirst.",
    body="Paragraph one.\n\nParagraph two.",
    category="news",
    tags=["bitcoin", "etf"],
)

OTHER_ARTICLE = ArticleContent(
    title="Ethereum Layer-2 Rollups Explained",
    summary="A different short standfirst.",
    body="Paragraph one.\n\nParagraph two.",
    category="news",
    tags=["ethereum", "l2"],
)


@pytest.fixture
def publisher_patches():
    with (
        patch(
            "app.publish.site_publisher.build_authenticated_url",
            return_value="https://fake-authenticated-url",
        ) as fake_build_url,
        patch("app.publish.site_publisher.clone_repo") as fake_clone,
        patch("app.publish.site_publisher.commit_and_push_with_retry") as fake_push,
        patch(
            "app.publish.site_publisher.download_thumbnail", return_value=MINIMAL_JPEG_200x100
        ) as fake_download,
    ):
        yield {
            "build_url": fake_build_url,
            "clone": fake_clone,
            "push": fake_push,
            "download": fake_download,
        }


def test_enter_clones_with_site_profile_details(sample_site_profile, publisher_patches):
    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        assert publisher is not None

    publisher_patches["build_url"].assert_called_once_with(
        sample_site_profile.repo_owner, sample_site_profile.repo_name, "fake-pat"
    )
    _, kwargs = publisher_patches["clone"].call_args
    assert kwargs["url"] == "https://fake-authenticated-url"
    assert kwargs["branch"] == sample_site_profile.default_branch


def test_exit_cleans_up_temp_directory(sample_site_profile, publisher_patches):
    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        clone_dir = publisher._clone_dir
        assert os.path.isdir(clone_dir)

    assert not os.path.exists(clone_dir)


def test_clone_failure_raises_publish_error_and_cleans_up(sample_site_profile, publisher_patches):
    publisher_patches["clone"].side_effect = GitOpsError("clone failed")

    with pytest.raises(PublishError, match="clone failed"):
        with SitePublisher(sample_site_profile, "fake-pat"):
            pass  # pragma: no cover -- __enter__ should raise first


def test_stage_writes_article_json_with_expected_fields(
    sample_video, sample_site_profile, publisher_patches
):
    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        slug = publisher.stage(sample_video, SAMPLE_ARTICLE)

        article_path = os.path.join(publisher._clone_dir, "content", "articles", f"{slug}.json")
        with open(article_path, encoding="utf-8") as f:
            data = json.load(f)

    assert data["title"] == SAMPLE_ARTICLE.title
    assert data["summary"] == SAMPLE_ARTICLE.summary
    assert data["body"] == SAMPLE_ARTICLE.body
    assert data["category"] == "news"
    assert data["tags"] == ["bitcoin", "etf"]
    assert data["sourceUrl"] == sample_video.watch_url
    assert data["sourceName"] == sample_video.channel_title
    assert data["youtubeVideoId"] == sample_video.video_id
    assert data["imageUrl"] == f"/images/articles/{slug}.jpg"
    assert data["imageWidth"] == 200
    assert data["imageHeight"] == 100
    assert data["slug"] == slug


def test_stage_falls_back_to_default_source_name_when_channel_title_empty(
    sample_video, sample_site_profile, publisher_patches
):
    video_no_channel = dataclasses.replace(sample_video, channel_title="")

    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        slug = publisher.stage(video_no_channel, SAMPLE_ARTICLE)
        article_path = os.path.join(publisher._clone_dir, "content", "articles", f"{slug}.json")
        with open(article_path, encoding="utf-8") as f:
            data = json.load(f)

    assert data["sourceName"] == sample_site_profile.default_source_name


def test_stage_writes_image_file(sample_video, sample_site_profile, publisher_patches):
    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        slug = publisher.stage(sample_video, SAMPLE_ARTICLE)
        image_path = os.path.join(publisher._clone_dir, "public", "images", "articles", f"{slug}.jpg")
        with open(image_path, "rb") as f:
            content = f.read()

    assert content == MINIMAL_JPEG_200x100


def test_stage_omits_dimensions_when_not_a_parseable_jpeg(
    sample_video, sample_site_profile, publisher_patches
):
    publisher_patches["download"].return_value = b"not a real jpeg"

    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        slug = publisher.stage(sample_video, SAMPLE_ARTICLE)
        article_path = os.path.join(publisher._clone_dir, "content", "articles", f"{slug}.json")
        with open(article_path, encoding="utf-8") as f:
            data = json.load(f)

    assert "imageWidth" not in data
    assert "imageHeight" not in data


def test_stage_wraps_image_download_error(sample_video, sample_site_profile, publisher_patches):
    publisher_patches["download"].side_effect = ImageDownloadError("download failed")

    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        with pytest.raises(PublishError, match="download failed"):
            publisher.stage(sample_video, SAMPLE_ARTICLE)


def test_stage_bumps_slug_on_collision(sample_video, sample_site_profile, publisher_patches):
    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        first_slug = publisher.stage(sample_video, SAMPLE_ARTICLE)
        second_slug = publisher.stage(sample_video, SAMPLE_ARTICLE)

    assert first_slug != second_slug
    assert second_slug == f"{first_slug}-2"
    # Staging -- even staging twice -- must never touch git.
    publisher_patches["push"].assert_not_called()


def test_stage_never_calls_commit_and_push(sample_video, sample_site_profile, publisher_patches):
    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        publisher.stage(sample_video, SAMPLE_ARTICLE)

    publisher_patches["push"].assert_not_called()


def test_push_all_does_nothing_when_nothing_staged(sample_site_profile, publisher_patches):
    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        result = publisher.push_all()

    assert result == 0
    publisher_patches["push"].assert_not_called()


def test_push_all_returns_number_of_staged_videos(
    sample_video, sample_site_profile, publisher_patches
):
    other_video = dataclasses.replace(sample_video, video_id="other456")

    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        publisher.stage(sample_video, SAMPLE_ARTICLE)
        publisher.stage(other_video, OTHER_ARTICLE)
        result = publisher.push_all()

    assert result == 2


def test_push_all_commits_all_staged_paths_in_one_call(
    sample_video, sample_site_profile, publisher_patches
):
    other_video = dataclasses.replace(sample_video, video_id="other456")

    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        slug1 = publisher.stage(sample_video, SAMPLE_ARTICLE)
        slug2 = publisher.stage(other_video, OTHER_ARTICLE)
        publisher.push_all()

    assert publisher_patches["push"].call_count == 1
    _, kwargs = publisher_patches["push"].call_args
    assert kwargs["paths_to_add"] == [
        f"content/articles/{slug1}.json",
        f"public/images/articles/{slug1}.jpg",
        f"content/articles/{slug2}.json",
        f"public/images/articles/{slug2}.jpg",
    ]


def test_push_all_commit_message_matches_single_video_format_when_only_one_staged(
    sample_video, sample_site_profile, publisher_patches
):
    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        publisher.stage(sample_video, SAMPLE_ARTICLE)
        publisher.push_all()

    _, kwargs = publisher_patches["push"].call_args
    assert kwargs["commit_message"] == (
        f"Add article from YouTube video {sample_video.video_id}: {SAMPLE_ARTICLE.title}"
    )


def test_push_all_commit_message_lists_all_staged_video_ids_and_titles_when_multiple(
    sample_video, sample_site_profile, publisher_patches
):
    other_video = dataclasses.replace(sample_video, video_id="other456")

    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        publisher.stage(sample_video, SAMPLE_ARTICLE)
        publisher.stage(other_video, OTHER_ARTICLE)
        publisher.push_all()

    _, kwargs = publisher_patches["push"].call_args
    message = kwargs["commit_message"]
    assert "Add 2 articles from YouTube videos" in message
    assert f"{sample_video.video_id}: {SAMPLE_ARTICLE.title}" in message
    assert f"{other_video.video_id}: {OTHER_ARTICLE.title}" in message


def test_push_all_wraps_git_ops_error(sample_video, sample_site_profile, publisher_patches):
    other_video = dataclasses.replace(sample_video, video_id="other456")
    publisher_patches["push"].side_effect = GitOpsError("push failed")

    with SitePublisher(sample_site_profile, "fake-pat") as publisher:
        publisher.stage(sample_video, SAMPLE_ARTICLE)
        publisher.stage(other_video, OTHER_ARTICLE)
        with pytest.raises(PublishError, match="push failed"):
            publisher.push_all()
