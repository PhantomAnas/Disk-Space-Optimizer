from __future__ import annotations

import os
import sys
import threading

import pytest

from conftest import make_file
from diskoptimizer import scanner
from diskoptimizer.scanner import Filter, apply, category_of, empty_folders, find_duplicates, human_size, list_drives


def test_human_size():
    assert human_size(0) == "0 B"
    assert human_size(1023) == "1023 B"
    assert human_size(1536) == "1.5 KB"
    assert human_size(5 * 1024 ** 3) == "5.0 GB"
    assert human_size(3 * 1024 ** 4) == "3.0 TB"


def test_category_of():
    assert category_of("a.MP4") == "Videos"
    assert category_of("x.jpeg") == "Images"
    assert category_of("setup.exe") == "Installers"
    assert category_of("model.pt") == "Models & data"
    assert category_of("noext") == "Other"
    assert set(scanner.CATEGORY_NAMES) >= {"Videos", "Other", "Code"}


def test_scan_sizes_counts_and_tree(tree):
    seen = []
    res = scanner.scan(tree, top_n=100, progress=lambda f, b, d: seen.append((f, b, d)), progress_every=0)
    assert res.total_files == 7 and res.total_bytes == 15_010_000 and res.skipped == 0
    assert [f.name for f in res.files[:3]] == ["movie.mp4", "setup.exe", "song.mp3"]
    assert res.files[-1].size == 0
    assert seen and seen[-1][0] == 7
    t = res.tree
    assert t.size == 15_010_000 and t.files == 7 and t.own_files == 2
    docs = t.children[os.path.join(tree, "docs")]
    assert docs.size == 4_010_000 and docs.files == 2 and docs.own_size == 10_000
    names = [c.name for c in t.sorted_children()]
    assert names[0] == "docs" and set(names[1:3]) == {"music", "photos"}   # music and photos tie at 3 MB
    assert sorted(os.path.basename(p) for p in empty_folders(t)) == ["also empty", "empty"]


def test_scan_keeps_only_top_n(tmp_path):
    root = str(tmp_path / "many")
    for i in range(300):
        make_file(os.path.join(root, f"f{i}.dat"), i * 10)
    res = scanner.scan(root, top_n=25)
    assert len(res.files) == 25 and res.total_files == 300
    assert [f.size for f in res.files] == sorted((i * 10 for i in range(300)), reverse=True)[:25]


def test_scan_cancel_and_errors(tree):
    ev = threading.Event()
    ev.set()
    res = scanner.scan(tree, cancelled=ev.is_set)
    assert res.cancelled and res.total_files == 0
    with pytest.raises(NotADirectoryError):
        scanner.scan(os.path.join(tree, "nope"))


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")
def test_scan_skips_junctions(tree, tmp_path):
    import subprocess
    link = str(tmp_path / "root" / "link")
    subprocess.run(["cmd", "/c", "mklink", "/J", link, os.path.join(tree, "photos")], capture_output=True, check=True)
    res = scanner.scan(tree)
    assert res.total_files == 7                      # photos counted once, not through the junction


def test_scan_skips_symlink_files(tree):
    target = os.path.join(tree, "movie.mp4")
    link = os.path.join(tree, "movie-link.mp4")
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted")
    assert scanner.scan(tree).total_files == 7


def test_filters(tree):
    files = scanner.scan(tree).files
    assert [f.name for f in apply(files, Filter(categories={"Images"}))] == ["a.jpg", "b.png"]
    assert [f.name for f in apply(files, Filter(text="DEEP"))] == ["setup.exe"]
    assert [f.name for f in apply(files, Filter(min_size=3_000_000))] == ["movie.mp4", "setup.exe", "song.mp3"]
    assert [f.name for f in apply(files, Filter(older_than_days=100))] == ["movie.mp4", "setup.exe"]
    assert [f.name for f in apply(files, Filter(not_used_days=30))] == ["movie.mp4", "setup.exe", "song.mp3"]
    assert apply(files, Filter(categories={"Videos"}, text="song")) == []


def test_sorting(tree):
    files = scanner.scan(tree).files
    assert [f.name for f in apply(files, None, "name", False)][:2] == ["a.jpg", "b.png"]
    assert [f.name for f in apply(files, None, "modified", True)][0] in ("b.png", "notes.txt", "tiny.bin")
    assert [f.name for f in apply(files, None, "modified", False)][0] == "movie.mp4"
    cats = [f.category for f in apply(files, None, "category", False)]
    assert cats == sorted(cats)
    assert [f.name for f in apply(files, None, "folder", False)][0] in ("movie.mp4", "tiny.bin")
    assert apply(files, None, "bogus")[0].name == "movie.mp4"


def test_entry_properties(tree):
    f = scanner.scan(tree).files[0]
    assert f.name == "movie.mp4" and f.ext == ".mp4" and f.category == "Videos" and f.folder == tree


def test_duplicates(tmp_path):
    root = str(tmp_path / "d")
    a = make_file(os.path.join(root, "a.bin"), 2_000_000)
    with open(a, "r+b") as fh:
        fh.write(b"hello")
    b = os.path.join(root, "copy of a.bin")
    with open(a, "rb") as src, open(b, "wb") as dst:
        dst.write(src.read())
    make_file(os.path.join(root, "same size different.bin"), 2_000_000)
    make_file(os.path.join(root, "small.bin"), 10)
    make_file(os.path.join(root, "small2.bin"), 10)
    files = scanner.scan(root).files
    groups = find_duplicates(files)
    assert len(groups) == 1 and sorted(f.name for f in groups[0]) == ["a.bin", "copy of a.bin"]
    assert find_duplicates(files, min_size=0)[-1][0].size == 10
    assert find_duplicates(files, cancelled=lambda: True) == []


def test_list_drives():
    drives = list_drives()
    assert drives and all(d.total >= d.free >= 0 and d.used >= 0 for d in drives)
