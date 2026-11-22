"""What the app refuses to touch, and the only way it removes anything:
the Recycle Bin (send2trash), logged so a session can be reviewed."""

from __future__ import annotations

import datetime as dt
import json
import os
import stat
import sys

from .settings import log_path


PROTECTED_ROOT_FILES = {"pagefile.sys", "hiberfil.sys", "swapfile.sys", "bootmgr", "bootnxt", "dumpstack.log.tmp", "ntldr"}

# Folders Windows creates at the root of every drive (restore points and the
# Recycle Bin).
ANY_DRIVE_SYSTEM_DIRS = {"$recycle.bin", "system volume information"}

# Folders Windows keeps at the root of the system drive for itself: boot and
# recovery data, and the working folders Windows Update and feature upgrades use.
SYSTEM_ROOT_DIRS = ANY_DRIVE_SYSTEM_DIRS | {
    "recovery", "boot", "efi", "config.msi", "$windows.~bt", "$windows.~ws", "$windows.~q",
    "$winreagent", "$sysreset", "$getcurrent", "windows.old", "esd", "msocache", "documents and settings",
}


def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def system_roots() -> list[str]:
    """Operating-system folders that are hidden from scans entirely (and never
    deleted): Windows itself, its update and upgrade caches, and the parts of
    Program Files / ProgramData / AppData that belong to Windows rather than
    to an app you installed.  Removing anything here can break Windows Update,
    Defender, Store apps or booting."""
    roots: list[str] = []
    if sys.platform == "win32":
        env = os.environ
        for key in ("WINDIR", "SYSTEMROOT"):
            if env.get(key):
                roots.append(env[key])
        sysdrive = env.get("SYSTEMDRIVE", "C:") + "\\"
        roots += [os.path.join(sysdrive, n) for n in sorted(SYSTEM_ROOT_DIRS)]
        for key in ("PROGRAMFILES", "PROGRAMW6432", "PROGRAMFILES(X86)"):
            if env.get(key):
                pf = env[key]
                roots += [os.path.join(pf, n) for n in ("WindowsApps", "ModifiableWindowsApps", "Windows Defender",
                                                        "Windows Defender Advanced Threat Protection", "Windows Mail",
                                                        "Windows Media Player", "Windows NT", "Windows Photo Viewer",
                                                        "Windows Portable Devices", "Windows Security", "Windows Sidebar",
                                                        "WindowsPowerShell")]
        if env.get("PROGRAMDATA"):
            pd = env["PROGRAMDATA"]
            roots += [os.path.join(pd, n) for n in ("Microsoft", "Package Cache", "Packages", "regid.1991-06.com.microsoft",
                                                    "USOPrivate", "USOShared", "WindowsHolographicDevices")]
        for key in ("APPDATA", "LOCALAPPDATA"):
            if env.get(key):
                roots.append(os.path.join(env[key], "Microsoft"))
        if env.get("LOCALAPPDATA"):
            roots.append(os.path.join(env["LOCALAPPDATA"], "Packages"))
    else:
        roots += ["/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/proc", "/run", "/sbin", "/sys",
                  "/usr", "/var", "/snap", "/System", "/Library", "/private", "/cores"]
    return list(dict.fromkeys(_norm(r) for r in roots))


def protected_roots() -> list[str]:
    """Folders that are never offered for deletion (and nothing inside them):
    everything in `system_roots()`, plus app and app-data folders that are
    shown in scans but are not yours to delete file by file."""
    roots = system_roots()
    if sys.platform == "win32":
        env = os.environ
        for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA", "PROGRAMW6432"):
            if env.get(key):
                roots.append(_norm(env[key]))
    else:
        roots.append(_norm("/Applications"))
    # The app itself (exe folder or checkout)
    here = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__)))
    roots.append(_norm(here))
    return list(dict.fromkeys(roots))


def is_drive_root(path: str) -> bool:
    return os.path.splitdrive(os.path.abspath(path))[1] in ("", os.sep, "/")


def is_system_file(path: str, attributes: int = 0) -> bool:
    """A file Windows owns: boot/page files at a drive root, or anything marked
    with the System attribute."""
    if os.path.basename(os.path.normcase(path)) in PROTECTED_ROOT_FILES and is_drive_root(os.path.dirname(path)):
        return True
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 0))


def protection_reason(path: str, roots: list[str] | None = None) -> str | None:
    """Why `path` must not be deleted, or None if it is fair game."""
    p = os.path.normcase(os.path.abspath(path))
    drive, tail = os.path.splitdrive(p)
    if tail in ("", os.sep, "/"):
        return "that is a whole drive"
    if os.path.basename(p) in PROTECTED_ROOT_FILES and os.path.dirname(p).rstrip("\\/") == drive:
        return "Windows system file"
    if sys.platform == "win32":
        first = tail.strip("\\/").split(os.sep, 1)[0]
        if first in ANY_DRIVE_SYSTEM_DIRS:
            return f"Windows system folder ({first})"
        try:
            if os.path.isfile(p) and is_system_file(p, os.stat(p, follow_symlinks=False).st_file_attributes):
                return "Windows system file"
        except (OSError, AttributeError):
            pass
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
