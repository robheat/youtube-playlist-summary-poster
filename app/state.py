"""Tracks which playlist videos have already been processed.

GitHub Actions runners are ephemeral, so this is persisted as a JSON file
that the workflow commits back into the repo after each run -- there is
nowhere else durable to keep it at this project's scale.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone


class StateFileError(RuntimeError):
    """Raised when the state file exists but contains malformed JSON.

    Never treated as "empty" on parse failure -- silently discarding a
    corrupt file could cause already-published videos to be reprocessed
    and republished.
    """


class StateStore:
    def __init__(self, path: str):
        self._path = path
        self._processed: dict[str, dict] = {}

    def load(self) -> None:
        if not os.path.exists(self._path):
            self._processed = {}
            return
        with open(self._path, "r", encoding="utf-8") as f:
            raw = f.read()
        if not raw.strip():
            self._processed = {}
            return
        try:
            self._processed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StateFileError(f"Malformed JSON in state file {self._path}: {exc}") from exc

    def is_processed(self, video_id: str) -> bool:
        return video_id in self._processed

    def mark_processed(self, video_id: str, title: str, *, status: str = "success") -> None:
        """Records a video as done. `status` is free-form text (not an
        enum) so a user can hand-edit the JSON file to add an entry with,
        e.g., status="skipped_manual" for a video that fails forever and
        should stop being retried -- is_processed() only checks key
        presence, not the status value, so this works with no extra code.
        """
        self._processed[video_id] = {
            "title": title,
            "status": status,
            "processed_at": _utc_now_iso(),
        }

    def save(self) -> None:
        """Atomic write: write to a temp file in the same directory, then
        os.replace() over the target, so a killed/cancelled job can't leave
        processed_videos.json half-written and corrupt.
        """
        directory = os.path.dirname(os.path.abspath(self._path)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".processed_videos_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._processed, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp_path, self._path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
