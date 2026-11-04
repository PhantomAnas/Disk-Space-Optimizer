from __future__ import annotations

import os
import sys

import pytest

from conftest import make_file
from diskoptimizer import cli, safety
from diskoptimizer import settings as settings_mod
from diskoptimizer.settings import Settings


def test_protection_reasons(tmp_path):
    roots = [os.path.normcase(str(tmp_path / "protected"))]
    assert safety.protection_reason(str(tmp_path / "protected" / "x.txt"), roots)
    assert safety.protection_reason(str(tmp_path / "protected"), roots)
    assert safety.protection_reason(str(tmp_path / "protectedX" / "x.txt"), roots) is None
    assert safety.protection_reason(str(tmp_path / "ok.txt"), roots) is None
    assert "drive" in safety.protection_reason("C:\\" if sys.platform == "win32" else "/", roots)
    assert safety.protection_reason(os.path.expanduser("~"), roots)
    if sys.platform == "win32":
        assert safety.protection_reason("C:\\pagefile.sys", roots) == "Windows system file"
        assert safety.protection_reason(os.path.join(os.environ["WINDIR"], "notepad.exe")) is not None
        assert safety.protection_reason(os.path.join(os.environ["PROGRAMFILES"], "App", "a.dll")) is not None
    assert any("diskoptimizer" in r.lower() or "disk-space-optimizer" in r.lower() for r in safety.protected_roots())


def test_send_to_trash_uses_send2trash_and_logs(tmp_path, monkeypatch):
    calls = []
    import send2trash as s2t
    monkeypatch.setattr(s2t, "send2trash", lambda p: calls.append(p))
    f = make_file(str(tmp_path / "junk.bin"), 100)
    safety.send_to_trash(f)
    safety.log_trashed(f, 100)
    assert calls == [f]
    log = safety.read_log()
    assert len(log) == 1 and log[0]["path"] == f and log[0]["size"] == 100
    with pytest.raises(safety.TrashError, match="no longer exists"):
        safety.send_to_trash(str(tmp_path / "missing.bin"))
    with pytest.raises(safety.TrashError, match="refused"):
        safety.send_to_trash(os.path.expanduser("~"))
    assert calls == [f]                                   # refused items never reach send2trash


def test_send_to_trash_errors_are_wrapped(tmp_path, monkeypatch):
    import send2trash as s2t

    def boom(p):
        raise OSError("locked")

    monkeypatch.setattr(s2t, "send2trash", boom)
    f = make_file(str(tmp_path / "x.bin"), 1)
    with pytest.raises(safety.TrashError, match="locked"):
        safety.send_to_trash(f)
    assert os.path.exists(f)


def test_real_send2trash_roundtrip(tmp_path):
    """The real library on a throw-away file (it lands in the Recycle Bin)."""
    f = make_file(str(tmp_path / "disk-space-optimizer-test.tmp"), 1)
    try:
        safety.send_to_trash(f)
    except safety.TrashError as exc:
        pytest.skip(f"recycle bin unavailable here: {exc}")
    assert not os.path.exists(f)


def test_settings_roundtrip(tmp_path):
    s = Settings(top_n=42, categories=["Videos"], sort_column="name", sort_descending=False)
    s.save()
    assert str(tmp_path) in settings_mod.config_path()
    loaded = Settings.load()
    assert loaded.top_n == 42 and loaded.categories == ["Videos"] and loaded.sort_column == "name"
    assert Settings.from_dict({"bogus": 1, "top_n": 7}).top_n == 7
    assert Settings.load(str(tmp_path / "none.json")).top_n == 500
    assert Settings(top_n=0, min_size_mb=-1, older_than_days=-5).validate() and Settings().validate() == []


def test_cli_scan_and_filters(tree, capsys):
    assert cli.main([tree, "--top", "3"]) == 0
    out = capsys.readouterr().out
    assert "7 files" in out and "movie.mp4" in out and "song.mp3" in out and "b.png" not in out
    assert cli.main([tree, "--category", "Images", "--sort", "name", "--folders", "--duplicates"]) == 0
    out = capsys.readouterr().out
    assert "a.jpg" in out and "movie.mp4" not in out.split("Biggest folders")[0] and "docs" in out and "duplicate group" in out
    assert cli.main([tree, "--older-than", "100", "--min-size", "4"]) == 0
    out = capsys.readouterr().out
    assert "movie.mp4" in out and "song.mp3" not in out


def test_cli_errors_and_drives(tmp_path, capsys):
    assert cli.main([]) == 2
    assert cli.main([str(tmp_path / "nope")]) == 2
    assert cli.main(["--drives"]) == 0
    assert "free" in capsys.readouterr().out
