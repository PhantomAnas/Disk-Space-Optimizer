"""Background workers: scanning, duplicate search, and recycling."""

from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QObject, QRunnable, Signal

from .. import safety, scanner


class ScanWorker(QObject):
    """Runs `scanner.scan` on a QThread; signals arrive on the GUI thread."""

    progress = Signal(int, int, str)      # files, bytes, folder
    finished = Signal(object)             # ScanResult
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()
        self.path = ""
        self.top_n = 500

    def start(self, path: str, top_n: int) -> None:
        self._cancel.clear()
        self.path, self.top_n = path, top_n

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            res = scanner.scan(self.path, self.top_n, progress=self.progress.emit, cancelled=self._cancel.is_set)
        except OSError as exc:
            self.failed.emit(str(exc))
            return
        except Exception:  # noqa: BLE001
            self.failed.emit("unexpected error:\n" + traceback.format_exc())
            return
        self.finished.emit(res)


class JobSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class DuplicatesJob(QRunnable):
    def __init__(self, files, signals: JobSignals, cancelled) -> None:
        super().__init__()
        self.files, self.signals, self.cancelled = list(files), signals, cancelled

    def run(self) -> None:
        try:
            self.signals.done.emit(scanner.find_duplicates(self.files, cancelled=self.cancelled))
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(str(exc))


class TrashJob(QRunnable):
    """Recycles paths one by one; emits (path, size, error-or-None) per item then the summary."""

    def __init__(self, items: list[tuple[str, int]], signals: "TrashSignals") -> None:
        super().__init__()
        self.items, self.signals = items, signals

    def run(self) -> None:
        ok, freed, errors = 0, 0, []
        for path, size in self.items:
            try:
                safety.send_to_trash(path)
                safety.log_trashed(path, size)
                ok += 1
                freed += size
                self.signals.item.emit(path, None)
            except safety.TrashError as exc:
                errors.append(f"{path}: {exc}")
                self.signals.item.emit(path, str(exc))
        self.signals.done.emit(ok, freed, errors)


class TrashSignals(QObject):
    item = Signal(str, object)
    done = Signal(int, int, list)
