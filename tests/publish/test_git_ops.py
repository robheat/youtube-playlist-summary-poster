"""Tests for app.publish.git_ops against a REAL local git repository.

Deliberately not mocked: mocking subprocess.run for a multi-step git
sequence would only prove "the right argv was passed," not that the
retry logic produces correct git semantics -- the one piece of this whole
publishing redesign most worth actually proving. Mirrors test_state.py's
existing precedent of testing against real file I/O rather than mocking.
"""
from __future__ import annotations

import subprocess

import pytest

from app.publish.git_ops import GitOpsError, build_authenticated_url, clone_repo, commit_and_push_with_retry


def _run(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, f"{args} failed: {result.stderr}"
    return result


def _seed_initial_commit(origin_path, scratch_dir) -> None:
    """Clones the (empty) bare origin, adds placeholder files under the
    two directories this app cares about, and pushes an initial commit --
    git can't commit directly into a bare repo."""
    seed_dir = scratch_dir / "seed"
    _run(["git", "clone", str(origin_path), str(seed_dir)])
    _run(["git", "config", "user.name", "Seed"], cwd=seed_dir)
    _run(["git", "config", "user.email", "seed@example.com"], cwd=seed_dir)
    (seed_dir / "content" / "articles").mkdir(parents=True)
    (seed_dir / "public" / "images" / "articles").mkdir(parents=True)
    (seed_dir / "content" / "articles" / ".gitkeep").write_text("")
    (seed_dir / "public" / "images" / "articles" / ".gitkeep").write_text("")
    (seed_dir / "some_other_dir").mkdir(parents=True)
    (seed_dir / "some_other_dir" / "other_stuff.txt").write_text("not part of the sparse checkout")
    # Cone-mode sparse-checkout always includes root-level files by design
    # (only subdirectories are actually excluded), so this root file is
    # NOT a useful exclusion check -- kept only as a sanity check that
    # root-level content still shows up.
    (seed_dir / "root_level_file.txt").write_text("always present in cone mode")
    _run(["git", "add", "-A"], cwd=seed_dir)
    _run(["git", "commit", "-m", "initial"], cwd=seed_dir)
    _run(["git", "push", "origin", "HEAD:main"], cwd=seed_dir)


def _plain_clone(origin_path, dest_path) -> None:
    """A plain (non-sparse) clone, used to act as an independent "other
    actor" pushing to origin -- deliberately not going through clone_repo()
    itself, so the test setup doesn't depend on the code under test."""
    _run(["git", "clone", str(origin_path), str(dest_path)])
    _run(["git", "config", "user.name", "Other Actor"], cwd=dest_path)
    _run(["git", "config", "user.email", "other@example.com"], cwd=dest_path)


@pytest.fixture
def origin(tmp_path):
    origin_path = tmp_path / "origin.git"
    _run(["git", "init", "--bare", "--initial-branch=main", str(origin_path)])
    _seed_initial_commit(origin_path, tmp_path)
    return origin_path


def test_build_authenticated_url_embeds_pat_and_repo():
    url = build_authenticated_url("someowner", "somerepo", "sometoken")
    assert url == "https://x-access-token:sometoken@github.com/someowner/somerepo.git"


def test_clone_repo_checks_out_only_the_sparse_paths(origin, tmp_path):
    dest = tmp_path / "ours"

    clone_repo(url=str(origin), branch="main", dest=str(dest))

    assert (dest / "content" / "articles" / ".gitkeep").exists()
    assert (dest / "public" / "images" / "articles" / ".gitkeep").exists()
    # some_other_dir/ is a subdirectory outside the sparse-checkout paths,
    # so cone-mode sparse-checkout should exclude it from disk. (A
    # root-level file would NOT be a valid exclusion check here -- cone
    # mode always materializes root-level files regardless of the
    # sparse-checkout set, by design.)
    assert not (dest / "some_other_dir").exists()
    assert (dest / "root_level_file.txt").exists()


def test_commit_and_push_returns_false_when_nothing_to_commit(origin, tmp_path):
    dest = tmp_path / "ours"
    clone_repo(url=str(origin), branch="main", dest=str(dest))

    result = commit_and_push_with_retry(
        repo_path=str(dest),
        branch="main",
        paths_to_add=["content/articles"],
        commit_message="no-op",
    )

    assert result is False


def test_commit_and_push_succeeds_with_no_conflict(origin, tmp_path):
    dest = tmp_path / "ours"
    clone_repo(url=str(origin), branch="main", dest=str(dest))
    (dest / "content" / "articles" / "our-article.json").write_text('{"slug": "our-article"}')

    result = commit_and_push_with_retry(
        repo_path=str(dest),
        branch="main",
        paths_to_add=["content/articles/our-article.json"],
        commit_message="Add our-article",
    )

    assert result is True

    verify_dir = tmp_path / "verify"
    _plain_clone(origin, verify_dir)
    assert (verify_dir / "content" / "articles" / "our-article.json").exists()


def test_commit_and_push_retries_and_succeeds_after_remote_moves(origin, tmp_path):
    ours = tmp_path / "ours"
    theirs = tmp_path / "theirs"
    clone_repo(url=str(origin), branch="main", dest=str(ours))
    _plain_clone(origin, theirs)

    # "theirs" pushes first, simulating the site's own daily pipeline
    # landing a commit while our job is mid-run -- exactly the race this
    # retry logic exists for.
    (theirs / "content" / "articles" / "their-article.json").write_text(
        '{"slug": "their-article"}'
    )
    _run(["git", "add", "content/articles/their-article.json"], cwd=theirs)
    _run(["git", "commit", "-m", "their commit"], cwd=theirs)
    _run(["git", "push", "origin", "HEAD:main"], cwd=theirs)

    # "ours" is now stale relative to origin -- a naive push would be rejected.
    (ours / "content" / "articles" / "our-article.json").write_text('{"slug": "our-article"}')

    result = commit_and_push_with_retry(
        repo_path=str(ours),
        branch="main",
        paths_to_add=["content/articles/our-article.json"],
        commit_message="Add our-article",
        max_attempts=3,
        retry_delay_seconds=0.01,
    )

    assert result is True

    verify_dir = tmp_path / "verify"
    _plain_clone(origin, verify_dir)
    assert (verify_dir / "content" / "articles" / "their-article.json").exists()
    assert (verify_dir / "content" / "articles" / "our-article.json").exists()


def test_commit_and_push_raises_and_resets_on_genuine_conflict(origin, tmp_path):
    ours = tmp_path / "ours"
    theirs = tmp_path / "theirs"
    clone_repo(url=str(origin), branch="main", dest=str(ours))
    _plain_clone(origin, theirs)

    # Both sides write DIFFERENT content to the SAME path -- a genuine,
    # unresolvable conflict. This app never does this in practice (every
    # real commit targets a brand-new unique slug), but the mechanism
    # must fail safely if it ever happened.
    (theirs / "content" / "articles" / "colliding.json").write_text('{"from": "theirs"}')
    _run(["git", "add", "content/articles/colliding.json"], cwd=theirs)
    _run(["git", "commit", "-m", "theirs"], cwd=theirs)
    _run(["git", "push", "origin", "HEAD:main"], cwd=theirs)

    (ours / "content" / "articles" / "colliding.json").write_text('{"from": "ours"}')

    with pytest.raises(GitOpsError):
        commit_and_push_with_retry(
            repo_path=str(ours),
            branch="main",
            paths_to_add=["content/articles/colliding.json"],
            commit_message="ours",
            max_attempts=2,
            retry_delay_seconds=0.01,
        )

    # The failed local commit must be discarded, not silently left around
    # to ride along with a future commit -- working tree clean, HEAD
    # matches what "theirs" actually published.
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ours, capture_output=True, text=True
    )
    assert status.stdout.strip() == ""
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=ours, capture_output=True, text=True)
    assert "theirs" in log.stdout
