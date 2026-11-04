"""What the app refuses to touch, and the only way it removes anything:
the Recycle Bin (send2trash), logged so a session can be reviewed."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

from .settings import log_path


def protected_roots() -> list[str]:
    """Folders that are never offered for deletion (and nothing inside them)."""
    roots: list[str] = []
    if sys.platform == "win32":
        env = os.environ
        for key in ("WINDIR", "SYSTEMROOT", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA", "PROGRAMW6432"):
            if env.get(key):
                roots.append(env[key])
        for key in ("APPDATA", "LOCALAPPDATA"):
            if env.get(key):
                roots.append(os.path.join(env[key], "Microsoft"))
        if env.get("LOCALAPPDATA"):
            roots.append(os.path.join(env["LOCALAPPDATA"], "Packages"))
        sysdrive = env.get("SYSTEMDRIVE", "C:") + "\\"
        roots += [os.path.join(sysdrive, n) for n in ("$Recycle.Bin", "System Volume Information", "Recovery", "Boot", "EFI")]
    else:
        roots += ["/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc", "/run", "/sbin", "/sys", "/usr", "/var",
                  "/System", "/Library", "/Applications", "/private"]
    # The app itself (exe folder or checkout)
    here = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__)))
    roots.append(here)
    return [os.path.normcase(os.path.abspath(r)) for r in roots]


PROTECTED_ROOT_FILES = {"pagefile.sys", "hiberfil.sys", "swapfile.sys", "bootmgr", "bootnxt", "dumpstack.log.tmp", "ntldr"}


def protection_reason(path: str, roots: list[str] | None = None) -> str | None:
    """Why `path` must not be deleted, or None if it is fair game."""
    p = os.path.normcase(os.path.abspath(path))
    drive, tail = os.path.splitdrive(p)
    if tail in ("", os.sep, "/"):
        return "that is a whole drive"
    if os.path.basename(p) in PROTECTED_ROOT_FILES and os.path.dirname(p).rstrip("\\/") == drive:
        return "Windows system file"
    for root in roots if roots is not None else protected_roots():
        if p == root or p.startswith(root.rstrip("\\/") + os.sep):
            return f"inside a protected folder ({root})"
    home = os.path.normcase(os.path.abspath(os.path.expanduser("~")))
    if p == home:
        return "your home folder"
    return None


class TrashError(Exception):
    pass


def send_to_trash(path: str) -> None:
    """Recycle one file or folder.  Raises TrashError with a readable reason."""
    reason = protection_reason(path)
    if reason:
        raise TrashError(f"refused: {reason}")
    if not os.path.lexists(path):
        raise TrashError("it no longer exists")
    try:
        from send2trash import send2trash
    except ImportError as exc:  # pragma: no cover
        raise TrashError("send2trash is not installed") from exc
    try:
        send2trash(path)
    except Exception as exc:  # noqa: BLE001 - send2trash raises OSError/TrashPermissionError variants
        raise TrashError(str(exc) or type(exc).__name__) from exc


def log_trashed(path: str, size: int) -> None:
    try:
        os.makedirs(os.path.dirname(log_path()), exist_ok=True)
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"when": dt.datetime.now().isoformat(timespec="seconds"), "path": path, "size": size}) + "\n")
    except OSError:
        pass


def read_log(limit: int = 500) -> list[dict]:
    try:
        with open(log_path(), "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out
