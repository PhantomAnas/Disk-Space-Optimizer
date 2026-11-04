"""Scanning a drive or folder: every file's size, dates and category, plus
per-folder totals.  Runs on a worker thread; reports progress; can be
cancelled; never follows symlinks or junctions; never dies on an unreadable
entry."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import string
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field

CATEGORIES: dict[str, set[str]] = {
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".3gp"},
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".heic", ".raw", ".cr2", ".nef", ".psd", ".svg", ".ico"},
    "Audio": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".mid"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".zst", ".cab", ".tgz"},
    "Installers": {".exe", ".msi", ".iso", ".img", ".dmg", ".apk", ".appx", ".msix", ".deb", ".rpm", ".pkg"},
    "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md", ".rtf", ".odt", ".ods", ".epub", ".csv"},
    "Code": {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".rb", ".php", ".html", ".css",
             ".json", ".xml", ".yml", ".yaml", ".toml", ".sh", ".ps1", ".bat", ".sql", ".ipynb"},
    "Models & data": {".pt", ".pth", ".onnx", ".safetensors", ".bin", ".ckpt", ".h5", ".npy", ".npz", ".parquet", ".db", ".sqlite"},
    "Virtual disks": {".vhd", ".vhdx", ".vmdk", ".vdi", ".qcow2", ".ova"},
}
CATEGORY_NAMES = list(CATEGORIES) + ["Other"]
_EXT_TO_CATEGORY = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts}


def category_of(name: str) -> str:
    return _EXT_TO_CATEGORY.get(os.path.splitext(name)[1].lower(), "Other")


def human_size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


@dataclass
class FileEntry:
    path: str
    size: int
    mtime: float
    atime: float

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def folder(self) -> str:
        return os.path.dirname(self.path)

    @property
    def category(self) -> str:
        return category_of(self.path)

    @property
    def ext(self) -> str:
        return os.path.splitext(self.path)[1].lower()


@dataclass
class FolderNode:
    path: str
    size: int = 0               # including subfolders
    own_size: int = 0           # files directly inside
    own_files: int = 0
    files: int = 0              # including subfolders
    children: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return os.path.basename(self.path.rstrip("\\/")) or self.path

    def sorted_children(self) -> list["FolderNode"]:
        return sorted(self.children.values(), key=lambda c: c.size, reverse=True)


@dataclass
class ScanResult:
    root: str
    files: list[FileEntry]          # the largest `top_n`, biggest first
    total_files: int
    total_bytes: int
    skipped: int                    # unreadable entries
    seconds: float
    tree: FolderNode
    cancelled: bool = False


class ScanCancelled(Exception):
    pass


def _is_reparse(entry: os.DirEntry) -> bool:
    if entry.is_symlink():
        return True
    if sys.platform == "win32":
        try:
            return bool(entry.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        except OSError:
            return True
    return False


def scan(root: str, top_n: int = 500, progress=None, cancelled=None, progress_every: float = 0.15) -> ScanResult:
    """Walk `root`.  `progress(files_seen, bytes_seen, current_folder)` is
    called at most every `progress_every` seconds; `cancelled()` is polled."""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise NotADirectoryError(root)
    t0 = time.time()
    files_seen = 0
    bytes_seen = 0
    skipped = 0
    last_report = 0.0
    tree = FolderNode(root)
    nodes: dict[str, FolderNode] = {root: tree}
    # Keep only the top N by size with a simple threshold: cheap and exact enough
    # because we sort at the end; the list is capped to 2*top_n periodically.
    kept: list[FileEntry] = []
    cap = max(2 * top_n, 2000)
    threshold = 0
    stack = [root]
    was_cancelled = False
    while stack:
        if cancelled and cancelled():
            was_cancelled = True
            break
        folder = stack.pop()
        try:
            it = os.scandir(folder)
        except OSError:
            skipped += 1
            continue
        node = nodes.get(folder)
        if node is None:
            node = FolderNode(folder)
            nodes[folder] = node
        with it:
            for entry in it:
                try:
                    if _is_reparse(entry):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        child = FolderNode(entry.path)
                        node.children[entry.path] = child
                        nodes[entry.path] = child
                        stack.append(entry.path)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    skipped += 1
                    continue
                size = st.st_size
                files_seen += 1
                bytes_seen += size
                node.own_size += size
                node.own_files += 1
                if size >= threshold or len(kept) < top_n:
                    kept.append(FileEntry(entry.path, size, st.st_mtime, st.st_atime))
                    if len(kept) > cap:
                        kept.sort(key=lambda f: f.size, reverse=True)
                        del kept[top_n:]
                        threshold = kept[-1].size
        now = time.time()
        if progress and now - last_report >= progress_every:
            last_report = now
            progress(files_seen, bytes_seen, folder)
    kept.sort(key=lambda f: f.size, reverse=True)
    del kept[top_n:]
    _roll_up(tree)
    if progress:
        progress(files_seen, bytes_seen, root)
    return ScanResult(root, kept, files_seen, bytes_seen, skipped, time.time() - t0, tree, was_cancelled)


def _roll_up(node: FolderNode) -> tuple[int, int]:
    size, files = node.own_size, node.own_files
    for child in node.children.values():
        s, f = _roll_up(child)
        size += s
        files += f
    node.size = size
    node.files = files
    return size, files


# ----------------------------------------------------------------- filtering

@dataclass
class Filter:
    categories: set | None = None       # None = all
    text: str = ""
    min_size: int = 0
    older_than_days: int = 0            # by modified date; 0 = any age
    not_used_days: int = 0              # by access date; 0 = any

    def matches(self, f: FileEntry, now: float | None = None) -> bool:
        now = now or time.time()
        if self.categories is not None and f.category not in self.categories:
            return False
        if f.size < self.min_size:
            return False
        if self.text and self.text.lower() not in f.path.lower():
            return False
        if self.older_than_days and now - f.mtime < self.older_than_days * 86400:
            return False
        if self.not_used_days and now - f.atime < self.not_used_days * 86400:
            return False
        return True


SORT_KEYS = {
    "size": lambda f: f.size,
    "name": lambda f: f.name.lower(),
    "category": lambda f: (f.category, -f.size),
    "modified": lambda f: f.mtime,
    "accessed": lambda f: f.atime,
    "folder": lambda f: f.folder.lower(),
}


def apply(files: list[FileEntry], flt: Filter | None = None, sort: str = "size", descending: bool = True) -> list[FileEntry]:
    out = [f for f in files if flt is None or flt.matches(f)]
    out.sort(key=SORT_KEYS.get(sort, SORT_KEYS["size"]), reverse=descending)
    return out


# ------------------------------------------------------------------- drives

@dataclass
class Drive:
    path: str
    total: int
    free: int
    label: str = ""

    @property
    def used(self) -> int:
        return self.total - self.free


def list_drives() -> list[Drive]:
    out: list[Drive] = []
    if sys.platform == "win32":
        import ctypes

        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if not mask & (1 << i):
                continue
            path = f"{letter}:\\"
            try:
                if ctypes.windll.kernel32.GetDriveTypeW(path) not in (3, 2):     # fixed, removable
                    continue
                usage = shutil.disk_usage(path)
            except OSError:
                continue
            label = ""
            try:
                buf = ctypes.create_unicode_buffer(261)
                if ctypes.windll.kernel32.GetVolumeInformationW(path, buf, 261, None, None, None, None, 0):
                    label = buf.value
            except OSError:
                pass
            out.append(Drive(path, usage.total, usage.free, label))
    else:
        for path in ("/", os.path.expanduser("~")):
            try:
                usage = shutil.disk_usage(path)
                out.append(Drive(path, usage.total, usage.free))
            except OSError:
                pass
    return out


# ---------------------------------------------------------------- duplicates

def find_duplicates(files: list[FileEntry], min_size: int = 1024 * 1024, cancelled=None) -> list[list[FileEntry]]:
    """Groups of identical files among `files` (same size, then same SHA-256 of the whole file)."""
    by_size: dict[int, list[FileEntry]] = defaultdict(list)
    for f in files:
        if f.size >= min_size:
            by_size[f.size].append(f)
    groups: list[list[FileEntry]] = []
    for size, same in by_size.items():
        if len(same) < 2:
            continue
        by_hash: dict[str, list[FileEntry]] = defaultdict(list)
        for f in same:
            if cancelled and cancelled():
                return groups
            h = _sha256(f.path)
            if h:
                by_hash[h].append(f)
        groups.extend(g for g in by_hash.values() if len(g) > 1)
    groups.sort(key=lambda g: g[0].size * (len(g) - 1), reverse=True)
    return groups


def _sha256(path: str) -> str | None:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def empty_folders(tree: FolderNode) -> list[str]:
    """Folders (deepest first) that contain no files at any depth."""
    out: list[str] = []

    def walk(node: FolderNode) -> bool:
        empty = node.own_files == 0
        for child in node.children.values():
            if not walk(child):
                empty = False
        if empty and node.path != tree.path:
            out.append(node.path)
        return empty

    walk(tree)
    return out
