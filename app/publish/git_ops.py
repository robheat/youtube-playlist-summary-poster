"""Low-level git operations for publishing into a separate site repo via a
cross-repo Personal Access Token.

Uses subprocess calls to the git CLI rather than a library (e.g.
GitPython) or the GitHub REST API. Git is already required for
actions/checkout, this matches the exact convention the target repos' own
daily-pipeline.yml workflows already use (raw git commands in a shell
step), and it gives full control over the shallow+sparse clone flags and
the atomic multi-file commit that the REST Contents API can't do in one
request.
"""
from __future__ import annotations

import subprocess
import time

BOT_NAME = "youtube-playlist-summary-poster[bot]"
BOT_EMAIL = "youtube-playlist-summary-poster@users.noreply.github.com"


class GitOpsError(RuntimeError):
    """Raised when a git operation fails unrecoverably."""


def _run(args: list[str], *, cwd: str | None) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GitOpsError(f"Command failed ({' '.join(args)}) in {cwd}: {result.stderr[:1000]}")
    return result


def build_authenticated_url(owner: str, repo: str, pat: str) -> str:
    return f"https://x-access-token:{pat}@github.com/{owner}/{repo}.git"


def clone_repo(url: str, branch: str, dest: str) -> None:
    """Shallow + partial + sparse clone into dest (must not already exist).

    Takes a ready-made URL rather than owner/repo/pat, so it can be
    pointed at any git remote (including a local path in tests) --
    build_authenticated_url() is the piece that knows about GitHub/PATs.

    This app only ever adds new files under content/articles/ and
    public/images/articles/, and never reads anything else, so there's no
    need for a full checkout -- ainformed-dev's own daily-pipeline.yml
    checkout step already does the same sparse-checkout for the same
    reason (public/images/articles/ is apparently large).
    """
    _run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--filter=blob:none",
            "--sparse",
            "--branch",
            branch,
            "--single-branch",
            url,
            dest,
        ],
        cwd=None,
    )
    _run(["git", "sparse-checkout", "set", "content/articles", "public/images/articles"], cwd=dest)
    _run(["git", "config", "user.name", BOT_NAME], cwd=dest)
    _run(["git", "config", "user.email", BOT_EMAIL], cwd=dest)


def commit_and_push_with_retry(
    repo_path: str,
    branch: str,
    paths_to_add: list[str],
    commit_message: str,
    *,
    max_attempts: int = 5,
    retry_delay_seconds: float = 5.0,
) -> bool:
    """Stages paths_to_add, commits, and pushes -- retrying on rejection by
    fetching and rebasing onto the latest remote branch.

    Called once per run with every staged video's paths batched into a
    single commit (see SitePublisher.push_all()), not once per video --
    this keeps Vercel's auto-deploy-on-push to a single rebuild per run.

    Safe to rebase here: this app's commits only ever ADD brand-new,
    uniquely-slugged files, never touching a path any other process would
    touch, so a rebase is always a clean linear replay unless there's a
    genuine slug collision (in which case it fails cleanly below and
    every video staged this run is retried next run, by which point the
    on-disk collision will make site_publisher.py bump the slug instead).

    Returns False if there was nothing to commit (paths_to_add matched no
    changes). Raises GitOpsError if the push still fails after
    max_attempts, after discarding the local commit so a failed push
    can't silently leave a dangling commit behind in the clone.
    """
    _run(["git", "add", *paths_to_add], cwd=repo_path)

    diff_check = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=repo_path, capture_output=True
    )
    if diff_check.returncode == 0:
        return False

    _run(["git", "commit", "-m", commit_message], cwd=repo_path)

    last_error = ""
    attempt = 0
    for attempt in range(1, max_attempts + 1):
        push = subprocess.run(
            ["git", "push", "origin", f"HEAD:{branch}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if push.returncode == 0:
            return True

        last_error = push.stderr
        if attempt == max_attempts:
            break

        time.sleep(retry_delay_seconds)
        _run(["git", "fetch", "origin", branch], cwd=repo_path)
        rebase = subprocess.run(
            ["git", "rebase", f"origin/{branch}"], cwd=repo_path, capture_output=True, text=True
        )
        if rebase.returncode != 0:
            subprocess.run(["git", "rebase", "--abort"], cwd=repo_path, capture_output=True)
            last_error = rebase.stderr
            break

    _reset_to_remote(repo_path, branch)
    raise GitOpsError(f"Push to {branch} failed after {attempt} attempt(s): {last_error[:1000]}")


def _reset_to_remote(repo_path: str, branch: str) -> None:
    """Discards any local commit that failed to push, leaving the clone's
    working tree consistent with origin. commit_and_push_with_retry is
    called at most once per run now (the whole batch in one commit -- see
    SitePublisher.push_all()), so this no longer guards against a second,
    later commit in the same run riding along with a failed one; it's
    just defensive cleanup of the (short-lived, about-to-be-deleted)
    clone directory."""
    subprocess.run(["git", "fetch", "origin", branch], cwd=repo_path, capture_output=True)
    subprocess.run(["git", "reset", "--hard", f"origin/{branch}"], cwd=repo_path, capture_output=True)
