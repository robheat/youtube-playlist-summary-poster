"""Tests for app.state.StateStore."""
from __future__ import annotations

import json

import pytest

from app.state import StateFileError, StateStore


def test_load_missing_file_starts_empty(tmp_path):
    store = StateStore(str(tmp_path / "processed.json"))
    store.load()
    assert store.is_processed("abc123") is False


def test_mark_processed_then_save_then_reload_round_trips(tmp_path):
    path = tmp_path / "processed.json"
    store = StateStore(str(path))
    store.load()
    store.mark_processed("abc123", "Some Title")
    store.save()

    reloaded = StateStore(str(path))
    reloaded.load()
    assert reloaded.is_processed("abc123") is True
    assert reloaded.is_processed("other") is False


def test_save_writes_sorted_pretty_json(tmp_path):
    path = tmp_path / "processed.json"
    store = StateStore(str(path))
    store.load()
    store.mark_processed("zzz", "Z Title")
    store.mark_processed("aaa", "A Title")
    store.save()

    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert list(data.keys()) == sorted(data.keys())
    assert "\n" in raw


def test_mark_processed_accepts_custom_status(tmp_path):
    path = tmp_path / "processed.json"
    store = StateStore(str(path))
    store.load()
    store.mark_processed("abc123", "Title", status="skipped_manual")
    store.save()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["abc123"]["status"] == "skipped_manual"


def test_load_malformed_json_raises(tmp_path):
    path = tmp_path / "processed.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = StateStore(str(path))
    with pytest.raises(StateFileError):
        store.load()


def test_load_empty_file_treated_as_empty_state(tmp_path):
    path = tmp_path / "processed.json"
    path.write_text("", encoding="utf-8")
    store = StateStore(str(path))
    store.load()
    assert store.is_processed("anything") is False


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "dir" / "processed.json"
    store = StateStore(str(path))
    store.load()
    store.mark_processed("abc123", "Title")
    store.save()
    assert path.exists()


def test_save_does_not_leave_temp_file_behind(tmp_path):
    path = tmp_path / "processed.json"
    store = StateStore(str(path))
    store.load()
    store.mark_processed("abc123", "Title")
    store.save()

    leftover = [p for p in tmp_path.iterdir() if p.name != "processed.json"]
    assert leftover == []
