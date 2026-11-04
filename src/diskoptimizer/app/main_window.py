"""The Disk Space Optimizer window."""

from __future__ import annotations

import ctypes
import datetime as dt
import os
import subprocess
import sys
import tempfile
import threading

from .. import __version__
from ..settings import APP_NAME, Settings


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    for attempt in (
        lambda: ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)),
        lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2),
        lambda: ctypes.windll.user32.SetProcessDPIAware(),
    ):
        try:
            attempt()
            return
        except Exception:  # noqa: BLE001
            continue


enable_dpi_awareness()

from PySide6.QtCore import QThread, QThreadPool, QTimer, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDesktopServices, QFont, QIcon  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import safety, scanner  # noqa: E402
from ..scanner import CATEGORY_NAMES, FileEntry, Filter, FolderNode, ScanResult, human_size, list_drives  # noqa: E402
from . import icons  # noqa: E402
from .theme import STYLESHEET  # noqa: E402
from .widgets import Backdrop, Chips, GlassCard, SizeBarDelegate, hint, pill, round_button  # noqa: E402
from .worker import DuplicatesJob, JobSignals, ScanWorker, TrashJob, TrashSignals  # noqa: E402

COLUMNS = ("name", "size", "category", "modified", "accessed", "folder")
HEADERS = ("Name", "Size", "Type", "Modified", "Last opened", "Folder")


def resource_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets"))
    return os.path.join(base, name)


def app_icon() -> QIcon:
    for name in ("icon.ico", "icon.png"):
        p = resource_path(name)
        if os.path.exists(p):
            return QIcon(p)
    return icons.icon("folder")


def fmt_date(ts: float) -> str:
    try:
        d = dt.datetime.fromtimestamp(ts)
    except (OverflowError, OSError, ValueError):
        return "?"
    days = (dt.datetime.now() - d).days
    if days < 1:
        return "today"
    if days < 30:
        return f"{days} d ago"
    if days < 365:
        return f"{days // 30} mo ago"
    return f"{days // 365} y ago"


def reveal(path: str) -> None:
    if sys.platform == "win32" and os.path.exists(path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.s = settings
        self.setWindowTitle("Disk Space Optimizer")
        self.setWindowIcon(app_icon())
        self.resize(1380, 860)
        self.setMinimumSize(1000, 640)
        self.result: ScanResult | None = None
        self.rows: list[FileEntry] = []
        self._dupe_cancel = threading.Event()
        self._job_signals = JobSignals()
        self._job_signals.done.connect(self._dupes_ready)
        self._job_signals.failed.connect(lambda m: self._status(f"duplicate search failed: {m}"))
        self._trash_signals = TrashSignals()
        self._trash_signals.item.connect(self._trash_item)
        self._trash_signals.done.connect(self._trash_done)
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(self._refresh_table)
        self.backdrop = Backdrop()
        self.setCentralWidget(self.backdrop)
        self.backdrop.set_image(self.s.extra.get("wallpaper"))
        self._build()
        self._build_worker()
        self._apply_settings()
        self._fill_drives()

    # ------------------------------------------------------------- layout
    def _build(self) -> None:
        root = QVBoxLayout(self.backdrop)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.pixmap("folder", 28, "#ffffff", dpr=self.devicePixelRatioF()))
        title = QLabel("Disk Space Optimizer")
        title.setObjectName("Title")
        header.addWidget(logo)
        header.addSpacing(6)
        header.addWidget(title)
        header.addStretch(1)
        self.wallpaper_btn = round_button("settings", "Change wallpaper")
        self.wallpaper_btn.clicked.connect(self._pick_wallpaper)
        header.addWidget(self.wallpaper_btn)
        root.addLayout(header)

        root.addWidget(self._scan_card())
        root.addWidget(self._results_card(), 1)

    def _scan_card(self) -> GlassCard:
        card = GlassCard("Scan", "search")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.drive_combo = QComboBox()
        self.drive_combo.setMinimumWidth(260)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Drive or folder to scan")
        self.browse_btn = pill("Folder", "folder", tooltip="Pick any folder")
        self.downloads_btn = pill("Downloads", "download", tooltip="Scan your Downloads folder")
        self.temp_btn = pill("Temp", "trash", tooltip="Scan the temporary files folder")
        self.scan_btn = pill("Scan", "play", "Go")
        self.cancel_btn = pill("Cancel", "stop", "Danger")
        self.cancel_btn.setEnabled(False)
        row.addWidget(self.drive_combo)
        row.addWidget(self.path_edit, 1)
        row.addWidget(self.browse_btn)
        row.addWidget(self.downloads_btn)
        row.addWidget(self.temp_btn)
        row.addWidget(self.scan_btn)
        row.addWidget(self.cancel_btn)
        card.body.addLayout(row)
        row2 = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(8)
        self.progress.setVisible(False)
        self.status_lbl = hint("Pick a drive or folder and press Scan. Nothing is deleted without your confirmation, and deletions go to the Recycle Bin.")
        row2.addWidget(self.status_lbl, 1)
        row2.addWidget(hint("Keep the largest"))
        self.top_spin = QSpinBox()
        self.top_spin.setRange(50, 100000)
        self.top_spin.setSingleStep(100)
        self.top_spin.setSuffix(" files")
        row2.addWidget(self.top_spin)
        card.body.addLayout(row2)
        card.body.addWidget(self.progress)
        self.drive_combo.currentIndexChanged.connect(self._drive_chosen)
        self.browse_btn.clicked.connect(self._browse)
        self.downloads_btn.clicked.connect(lambda: self._scan_path(os.path.join(os.path.expanduser("~"), "Downloads")))
        self.temp_btn.clicked.connect(lambda: self._scan_path(tempfile.gettempdir()))
        self.scan_btn.clicked.connect(lambda: self._scan_path(self.path_edit.text().strip()))
        self.path_edit.returnPressed.connect(lambda: self._scan_path(self.path_edit.text().strip()))
        self.cancel_btn.clicked.connect(self._cancel)
        return card

    def _results_card(self) -> GlassCard:
        card = GlassCard()
        self.tabs = QTabWidget()
        self.tabs.addTab(self._files_tab(), "Largest files")
        self.tabs.addTab(self._folders_tab(), "Folders")
        self.tabs.addTab(self._dupes_tab(), "Duplicates")
        self.tabs.addTab(self._log_tab(), "Recycled this session")
        card.body.addWidget(self.tabs, 1)
        return card

    def _files_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(10)
        self.chips = Chips(CATEGORY_NAMES)
        lay.addWidget(self.chips)
        frow = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name or path")
        self.search.setClearButtonEnabled(True)
        self.min_size = QDoubleSpinBox()
        self.min_size.setRange(0, 100000)
        self.min_size.setDecimals(1)
        self.min_size.setPrefix("at least ")
        self.min_size.setSuffix(" MB")
        self.older = QSpinBox()
        self.older.setRange(0, 3650)
        self.older.setPrefix("not modified for ")
        self.older.setSuffix(" days")
        self.older.setSpecialValueText("any age")
        self.unused = QSpinBox()
        self.unused.setRange(0, 3650)
        self.unused.setPrefix("not opened for ")
        self.unused.setSuffix(" days")
        self.unused.setSpecialValueText("any last-opened")
        frow.addWidget(self.search, 1)
        frow.addWidget(self.min_size)
        frow.addWidget(self.older)
        frow.addWidget(self.unused)
        lay.addLayout(frow)
        self.table = QTreeWidget()
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHeaderLabels(HEADERS)
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(False)
        self.table.setUniformRowHeights(True)
        self.table.setItemDelegateForColumn(1, SizeBarDelegate(self.table))
        hdr = self.table.header()
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        hdr.sectionClicked.connect(self._sort_clicked)
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        for i, width in enumerate((300, 190, 110, 100, 110, 400)):
            self.table.setColumnWidth(i, width)
        lay.addWidget(self.table, 1)
        brow = QHBoxLayout()
        self.shown_lbl = hint("")
        self.selected_lbl = hint("")
        self.reveal_btn = pill("Show in Explorer", "open")
        self.open_btn = pill("Open", "play")
        self.trash_btn = pill("Recycle selected", "trash", "Danger")
        brow.addWidget(self.shown_lbl, 1)
        brow.addWidget(self.selected_lbl)
        brow.addWidget(self.reveal_btn)
        brow.addWidget(self.open_btn)
        brow.addWidget(self.trash_btn)
        lay.addLayout(brow)
        self.chips.changed.connect(lambda _s: self._filter_timer.start())
        self.search.textChanged.connect(lambda _t: self._filter_timer.start())
        self.min_size.valueChanged.connect(lambda _v: self._filter_timer.start())
        self.older.valueChanged.connect(lambda _v: self._filter_timer.start())
        self.unused.valueChanged.connect(lambda _v: self._filter_timer.start())
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda item, _c: reveal(item.data(0, Qt.ItemDataRole.UserRole)))
        self.reveal_btn.clicked.connect(self._reveal_selected)
        self.open_btn.clicked.connect(self._open_selected)
        self.trash_btn.clicked.connect(self._trash_selected)
        return w

    def _folders_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(hint("Every folder with its total size (subfolders included). Expand to drill down; double-click opens it in Explorer."))
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Folder", "Size", "Files"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setItemDelegateForColumn(1, SizeBarDelegate(self.tree))
        self.tree.setColumnWidth(0, 520)
        self.tree.setColumnWidth(1, 220)
        self.tree.header().setStretchLastSection(True)
        lay.addWidget(self.tree, 1)
        brow = QHBoxLayout()
        self.folder_lbl = hint("")
        self.folder_open_btn = pill("Open folder", "open")
        self.folder_trash_btn = pill("Recycle folder", "trash", "Danger")
        brow.addWidget(self.folder_lbl, 1)
        brow.addWidget(self.folder_open_btn)
        brow.addWidget(self.folder_trash_btn)
        lay.addLayout(brow)
        self.tree.itemExpanded.connect(self._expand_folder)
        self.tree.itemDoubleClicked.connect(lambda item, _c: QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(0, Qt.ItemDataRole.UserRole))))
        self.folder_open_btn.clicked.connect(self._open_folder)
        self.folder_trash_btn.clicked.connect(self._trash_folders)
        return w

    def _dupes_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(10)
        row = QHBoxLayout()
        self.dupes_btn = pill("Find duplicates among the largest files", "copy")
        self.dupes_lbl = hint("Files with identical content (same size and SHA-256). Keep one, recycle the rest.")
        row.addWidget(self.dupes_btn)
        row.addWidget(self.dupes_lbl, 1)
        lay.addLayout(row)
        self.dupes = QTreeWidget()
        self.dupes.setColumnCount(4)
        self.dupes.setHeaderLabels(["File", "Size", "Modified", "Folder"])
        self.dupes.setAlternatingRowColors(True)
        self.dupes.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.dupes.setColumnWidth(0, 360)
        self.dupes.setColumnWidth(1, 120)
        self.dupes.header().setStretchLastSection(True)
        lay.addWidget(self.dupes, 1)
        brow = QHBoxLayout()
        self.dupes_select_btn = pill("Select all but the newest in each group", "check")
        self.dupes_trash_btn = pill("Recycle selected", "trash", "Danger")
        brow.addStretch(1)
        brow.addWidget(self.dupes_select_btn)
        brow.addWidget(self.dupes_trash_btn)
        lay.addLayout(brow)
        self.dupes_btn.clicked.connect(self._find_dupes)
        self.dupes_select_btn.clicked.connect(self._select_dupes)
        self.dupes_trash_btn.clicked.connect(self._trash_dupes)
        self.dupes.itemDoubleClicked.connect(lambda item, _c: item.parent() and reveal(item.data(0, Qt.ItemDataRole.UserRole)))
        return w

    def _log_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(hint("Everything recycled by this app. Open the Recycle Bin to restore any of it."))
        self.log = QTreeWidget()
        self.log.setColumnCount(3)
        self.log.setHeaderLabels(["When", "Size", "Path"])
        self.log.setColumnWidth(0, 160)
        self.log.setColumnWidth(1, 110)
        self.log.header().setStretchLastSection(True)
        lay.addWidget(self.log, 1)
        row = QHBoxLayout()
        self.freed_lbl = hint("")
        self.bin_btn = pill("Open Recycle Bin", "open")
        row.addWidget(self.freed_lbl, 1)
        row.addWidget(self.bin_btn)
        lay.addLayout(row)
        self.bin_btn.clicked.connect(self._open_bin)
        for entry in safety.read_log():
            self._log_row(entry.get("when", ""), int(entry.get("size", 0) or 0), entry.get("path", ""))
        return w

    # ------------------------------------------------------------- worker
    def _build_worker(self) -> None:
        self.thread = QThread(self)
        self.worker = ScanWorker()
        self.worker.moveToThread(self.thread)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.thread.started.connect(self.worker.run)

    # ----------------------------------------------------------- settings
    def _apply_settings(self) -> None:
        s = self.s
        self.top_spin.setValue(s.top_n)
        self.min_size.setValue(s.min_size_mb)
        self.older.setValue(s.older_than_days)
        self.chips.set_value(s.categories)
        self.path_edit.setText(s.last_path)
        self._sort = s.sort_column if s.sort_column in COLUMNS else "size"
        self._desc = s.sort_descending
        idx = COLUMNS.index(self._sort)
        self.table.header().setSortIndicator(idx, Qt.SortOrder.DescendingOrder if self._desc else Qt.SortOrder.AscendingOrder)

    def _collect_settings(self) -> Settings:
        s = self.s
        s.top_n = self.top_spin.value()
        s.min_size_mb = self.min_size.value()
        s.older_than_days = self.older.value()
        s.categories = sorted(self.chips.value())
        s.last_path = self.path_edit.text().strip()
        s.sort_column, s.sort_descending = self._sort, self._desc
        return s

    def _save_settings(self) -> None:
        try:
            self._collect_settings().save()
        except OSError:
            pass

    # ---------------------------------------------------------- scanning
    def _fill_drives(self) -> None:
        self.drive_combo.blockSignals(True)
        self.drive_combo.clear()
        self.drive_combo.addItem("Choose a drive...", "")
        for d in list_drives():
            label = f"{d.path}  {d.label}".rstrip() + f"   {human_size(d.used)} used, {human_size(d.free)} free"
            self.drive_combo.addItem(label, d.path)
        self.drive_combo.blockSignals(False)

    def _drive_chosen(self, _idx: int) -> None:
        path = self.drive_combo.currentData()
        if path:
            self.path_edit.setText(path)

    def _browse(self) -> None:
        start = self.path_edit.text().strip() or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Folder to scan", start)
        if folder:
            self.path_edit.setText(os.path.normpath(folder))
            self._scan_path(os.path.normpath(folder))

    def _scan_path(self, path: str) -> None:
        if self.thread.isRunning():
            return
        if not path or not os.path.isdir(path):
            QMessageBox.warning(self, "Disk Space Optimizer", "Choose a drive or an existing folder first.")
            return
        self.path_edit.setText(path)
        self._save_settings()
        self.result = None
        self.table.clear()
        self.tree.clear()
        self.dupes.clear()
        self.worker.start(path, self.top_spin.value())
        self._set_busy(True)
        self._status(f"Scanning {path} ...")
        self.thread.start()

    def _cancel(self) -> None:
        self.worker.cancel()
        self.cancel_btn.setEnabled(False)
        self._status("Stopping...")

    def _set_busy(self, busy: bool) -> None:
        for w in (self.scan_btn, self.browse_btn, self.downloads_btn, self.temp_btn, self.drive_combo, self.trash_btn,
                  self.folder_trash_btn, self.dupes_btn, self.dupes_trash_btn):
            w.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.progress.setVisible(busy)

    def _on_progress(self, files: int, nbytes: int, folder: str) -> None:
        self._status(f"{files:,} files, {human_size(nbytes)} so far ... {folder}")

    def _finish_thread(self) -> None:
        self.thread.quit()
        self.thread.wait(5000)
        self._set_busy(False)

    def _on_finished(self, res: ScanResult) -> None:
        self._finish_thread()
        self.result = res
        note = " (stopped early)" if res.cancelled else ""
        skipped = f", {res.skipped} unreadable skipped" if res.skipped else ""
        self._status(f"{res.root}: {res.total_files:,} files, {human_size(res.total_bytes)} in {res.seconds:.1f}s{skipped}{note}")
        self._refresh_table()
        self._fill_tree()

    def _on_failed(self, msg: str) -> None:
        self._finish_thread()
        self._status("Scan failed")
        QMessageBox.critical(self, "Scan failed", msg)

    def _status(self, text: str) -> None:
        self.status_lbl.setText(text)

    # ------------------------------------------------------------- table
    def _current_filter(self) -> Filter:
        cats = self.chips.value()
        return Filter(categories=cats or None, text=self.search.text().strip(),
                      min_size=int(self.min_size.value() * 1024 * 1024), older_than_days=self.older.value(),
                      not_used_days=self.unused.value())

    def _refresh_table(self) -> None:
        self.table.clear()
        if self.result is None:
            self.shown_lbl.setText("")
            return
        self.rows = scanner.apply(self.result.files, self._current_filter(), self._sort, self._desc)
        biggest = max((f.size for f in self.rows), default=1)
        items = []
        for f in self.rows:
            it = QTreeWidgetItem([f.name, human_size(f.size), f.category, fmt_date(f.mtime), fmt_date(f.atime), f.folder])
            it.setData(0, Qt.ItemDataRole.UserRole, f.path)
            it.setData(1, Qt.ItemDataRole.UserRole, f.size / biggest)
            it.setToolTip(0, f.path)
            it.setToolTip(3, dt.datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d %H:%M"))
            it.setToolTip(4, dt.datetime.fromtimestamp(f.atime).strftime("%Y-%m-%d %H:%M"))
            items.append(it)
        self.table.addTopLevelItems(items)
        total = sum(f.size for f in self.rows)
        self.shown_lbl.setText(f"{len(self.rows):,} of the {len(self.result.files):,} largest files shown, {human_size(total)}")
        self._selection_changed()
        self._collect_settings()

    def _sort_clicked(self, col: int) -> None:
        key = COLUMNS[col]
        if key == self._sort:
            self._desc = not self._desc
        else:
            self._sort, self._desc = key, key in ("size", "modified", "accessed")
        self.table.header().setSortIndicator(col, Qt.SortOrder.DescendingOrder if self._desc else Qt.SortOrder.AscendingOrder)
        self._refresh_table()

    def _selected_files(self) -> list[tuple[str, int]]:
        by_path = {f.path: f.size for f in self.rows}
        return [(it.data(0, Qt.ItemDataRole.UserRole), by_path.get(it.data(0, Qt.ItemDataRole.UserRole), 0))
                for it in self.table.selectedItems()]

    def _selection_changed(self) -> None:
        sel = self._selected_files()
        self.selected_lbl.setText(f"{len(sel)} selected, {human_size(sum(s for _p, s in sel))}" if sel else "")

    def _reveal_selected(self) -> None:
        for path, _s in self._selected_files()[:5]:
            reveal(path)

    def _open_selected(self) -> None:
        for path, _s in self._selected_files()[:3]:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------- trash
    def _confirm_and_trash(self, items: list[tuple[str, int]], what: str) -> None:
        if not items:
            QMessageBox.information(self, "Disk Space Optimizer", f"Select some {what} first.")
            return
        refused = [(p, safety.protection_reason(p)) for p, _s in items]
        refused = [(p, r) for p, r in refused if r]
        if refused:
            QMessageBox.warning(self, "Protected", "These will not be touched:\n\n" +
                                "\n".join(f"{p}\n   {r}" for p, r in refused[:8]))
            items = [(p, s) for p, s in items if not safety.protection_reason(p)]
            if not items:
                return
        total = sum(s for _p, s in items)
        preview = "\n".join(p for p, _s in items[:12]) + (f"\n... and {len(items) - 12} more" if len(items) > 12 else "")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Move to Recycle Bin?")
        box.setText(f"Move {len(items)} {what} ({human_size(total)}) to the Recycle Bin?")
        box.setInformativeText("You can restore them from the Recycle Bin afterwards.")
        box.setDetailedText(preview)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        self._status(f"Recycling {len(items)} {what} ...")
        QThreadPool.globalInstance().start(TrashJob(items, self._trash_signals))

    def _trash_selected(self) -> None:
        self._confirm_and_trash(self._selected_files(), "files")

    def _trash_folders(self) -> None:
        items = []
        for it in self.tree.selectedItems():
            path = it.data(0, Qt.ItemDataRole.UserRole)
            size = it.data(1, Qt.ItemDataRole.UserRole + 1) or 0
            if self.result and os.path.normcase(path) == os.path.normcase(self.result.root):
                QMessageBox.warning(self, "Disk Space Optimizer", "The scanned root itself is not offered for deletion; pick a folder inside it.")
                return
            items.append((path, int(size)))
        self._confirm_and_trash(items, "folders")

    def _trash_dupes(self) -> None:
        items = []
        for it in self.dupes.selectedItems():
            if it.parent() is not None:
                items.append((it.data(0, Qt.ItemDataRole.UserRole), int(it.data(1, Qt.ItemDataRole.UserRole) or 0)))
        self._confirm_and_trash(items, "duplicate files")

    def _trash_item(self, path: str, error) -> None:
        if error:
            return
        self._log_row(dt.datetime.now().strftime("%Y-%m-%d %H:%M"), self._size_of(path), path)
        # drop it from the current views
        if self.result:
            self.result.files = [f for f in self.result.files if not (f.path == path or f.path.startswith(path.rstrip("\\/") + os.sep))]

    def _size_of(self, path: str) -> int:
        if self.result:
            for f in self.result.files:
                if f.path == path:
                    return f.size
        return 0

    def _trash_done(self, ok: int, freed: int, errors: list) -> None:
        self._set_busy(False)
        self.progress.setVisible(False)
        self._status(f"Recycled {ok} item(s), {human_size(freed)} freed" + (f", {len(errors)} failed" if errors else ""))
        if errors:
            QMessageBox.warning(self, "Some items could not be recycled", "\n".join(errors[:10]))
        self._refresh_table()
        if ok:
            self._fill_tree(rescan_note=True)
            self.dupes.clear()

    def _log_row(self, when: str, size: int, path: str) -> None:
        it = QTreeWidgetItem([when, human_size(size), path])
        self.log.insertTopLevelItem(0, it)
        self._freed = getattr(self, "_freed", 0) + size
        self.freed_lbl.setText(f"{self.log.topLevelItemCount()} item(s) recycled, {human_size(self._freed)} in total")

    def _open_bin(self) -> None:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "shell:RecycleBinFolder"])

    # ------------------------------------------------------------ folders
    def _fill_tree(self, rescan_note: bool = False) -> None:
        self.tree.clear()
        if self.result is None:
            return
        root_item = self._folder_item(self.result.tree, self.result.tree.size or 1)
        self.tree.addTopLevelItem(root_item)
        root_item.setExpanded(True)
        self.folder_lbl.setText("Sizes are from the last scan; recycle something and scan again to refresh." if rescan_note else
                                f"{len(self.result.tree.children)} folders at the top level")

    def _folder_item(self, node: FolderNode, biggest: int) -> QTreeWidgetItem:
        it = QTreeWidgetItem([node.name if node.path != self.result.root else node.path, human_size(node.size), f"{node.files:,}"])
        it.setData(0, Qt.ItemDataRole.UserRole, node.path)
        it.setData(1, Qt.ItemDataRole.UserRole, node.size / biggest if biggest else 0)
        it.setData(1, Qt.ItemDataRole.UserRole + 1, node.size)
        it.setData(0, Qt.ItemDataRole.UserRole + 1, node)
        it.setToolTip(0, node.path)
        if node.children:
            it.addChild(QTreeWidgetItem(["..."]))      # placeholder, filled on expand
        return it

    def _expand_folder(self, item: QTreeWidgetItem) -> None:
        if item.childCount() == 1 and item.child(0).text(0) == "...":
            item.takeChild(0)
            node: FolderNode = item.data(0, Qt.ItemDataRole.UserRole + 1)
            biggest = node.size or 1
            for child in node.sorted_children()[:300]:
                item.addChild(self._folder_item(child, biggest))

    def _open_folder(self) -> None:
        for it in self.tree.selectedItems()[:3]:
            QDesktopServices.openUrl(QUrl.fromLocalFile(it.data(0, Qt.ItemDataRole.UserRole)))

    # --------------------------------------------------------- duplicates
    def _find_dupes(self) -> None:
        if self.result is None:
            QMessageBox.information(self, "Disk Space Optimizer", "Scan a drive or folder first.")
            return
        self._dupe_cancel.clear()
        self.dupes.clear()
        self.dupes_btn.setEnabled(False)
        self.dupes_lbl.setText("Hashing files of equal size ...")
        QThreadPool.globalInstance().start(DuplicatesJob(self.result.files, self._job_signals, self._dupe_cancel.is_set))

    def _dupes_ready(self, groups: list) -> None:
        self.dupes_btn.setEnabled(True)
        self.dupes.clear()
        wasted = 0
        for g in groups:
            top = QTreeWidgetItem([f"{len(g)} identical copies", human_size(g[0].size), "", ""])
            top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for f in g:
                it = QTreeWidgetItem([f.name, human_size(f.size), fmt_date(f.mtime), f.folder])
                it.setData(0, Qt.ItemDataRole.UserRole, f.path)
                it.setData(1, Qt.ItemDataRole.UserRole, f.size)
                it.setData(0, Qt.ItemDataRole.UserRole + 1, f.mtime)
                it.setToolTip(0, f.path)
                top.addChild(it)
            wasted += g[0].size * (len(g) - 1)
            self.dupes.addTopLevelItem(top)
            top.setExpanded(True)
        self.dupes_lbl.setText(f"{len(groups)} group(s) of identical files, {human_size(wasted)} could be freed" if groups
                               else "No duplicates among the largest files.")

    def _select_dupes(self) -> None:
        self.dupes.clearSelection()
        for i in range(self.dupes.topLevelItemCount()):
            top = self.dupes.topLevelItem(i)
            kids = [top.child(k) for k in range(top.childCount())]
            newest = max(kids, key=lambda c: c.data(0, Qt.ItemDataRole.UserRole + 1) or 0)
            for c in kids:
                if c is not newest:
                    c.setSelected(True)

    # ------------------------------------------------------------- misc
    def _pick_wallpaper(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Wallpaper image (Cancel to reset)", os.path.expanduser("~"),
                                              "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        self.s.extra["wallpaper"] = path or ""
        self.backdrop.set_image(path)
        self._save_settings()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.thread.isRunning():
            self.worker.cancel()
            self.thread.quit()
            self.thread.wait(10000)
        self._dupe_cancel.set()
        self._save_settings()
        QThreadPool.globalInstance().waitForDone(3000)
        event.accept()


def main(argv: list[str] | None = None) -> int:
    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(app_icon())
    win = MainWindow(Settings.load())
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
