from __future__ import annotations

import os
import time

import pytest


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr("diskoptimizer.settings.config_path", lambda: str(tmp_path / "cfg" / "settings.json"))
    monkeypatch.setattr("diskoptimizer.settings.log_path", lambda: str(tmp_path / "cfg" / "trash-log.jsonl"))
    monkeypatch.setattr("diskoptimizer.safety.log_path", lambda: str(tmp_path / "cfg" / "trash-log.jsonl"))


def make_file(path: str, size: int, age_days: float = 0.0) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        if size:
            fh.seek(size - 1)
            fh.write(b"\0")
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return path


@pytest.fixture
def tree(tmp_path) -> str:
    """A small folder tree with known sizes, ages and categories."""
    root = str(tmp_path / "root")
    make_file(os.path.join(root, "movie.mp4"), 5_000_000, age_days=400)
    make_file(os.path.join(root, "photos", "a.jpg"), 2_000_000, age_days=10)
    make_file(os.path.join(root, "photos", "b.png"), 1_000_000)
    make_file(os.path.join(root, "music", "song.mp3"), 3_000_000, age_days=50)
    make_file(os.path.join(root, "docs", "notes.txt"), 10_000)
    make_file(os.path.join(root, "docs", "deep", "deeper", "setup.exe"), 4_000_000, age_days=200)
    make_file(os.path.join(root, "tiny.bin"), 0)
    os.makedirs(os.path.join(root, "empty", "also empty"), exist_ok=True)
    return root
