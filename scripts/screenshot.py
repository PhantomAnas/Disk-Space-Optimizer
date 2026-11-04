"""Render the main window on a generated demo tree and save docs/screenshot.png.

    python scripts/screenshot.py

Uses a throw-away settings file and a temp folder, so nothing personal
appears in the picture.  On Windows the window appears for a moment.
"""

from __future__ import annotations

import os
import random
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import diskoptimizer.settings as settings_mod  # noqa: E402

tmp = tempfile.mkdtemp(prefix="disk-optimizer-shot-")
settings_mod.config_path = lambda: os.path.join(tmp, "settings.json")  # type: ignore[assignment]
settings_mod.log_path = lambda: os.path.join(tmp, "log.jsonl")  # type: ignore[assignment]

DEMO = [
    ("Videos/Holiday 2024/beach-day.mp4", 2_400_000_000, 300), ("Videos/Holiday 2024/sunset-timelapse.mov", 1_100_000_000, 290),
    ("Videos/Screen recordings/tutorial-take-3.mkv", 850_000_000, 40), ("Downloads/ubuntu-24.04-desktop.iso", 5_900_000_000, 500),
    ("Downloads/game-installer.exe", 3_200_000_000, 410), ("Downloads/photos-backup.zip", 1_700_000_000, 120),
    ("Downloads/photos-backup (1).zip", 1_700_000_000, 118), ("Pictures/Camera/IMG_2041.heic", 9_000_000, 20),
    ("Pictures/Camera/IMG_2042.heic", 8_700_000, 20), ("Pictures/wallpaper-4k.png", 24_000_000, 600),
    ("Music/album-flac/01 Intro.flac", 48_000_000, 800), ("Music/album-flac/02 Track two.flac", 61_000_000, 800),
    ("Documents/thesis-final-FINAL.docx", 14_000_000, 90), ("Documents/scans/contract.pdf", 6_000_000, 700),
    ("Projects/ml/weights/yolo11x.pt", 220_000_000, 60), ("Projects/ml/data/train.parquet", 410_000_000, 61),
    ("VirtualBox VMs/win11-test.vdi", 24_000_000_000, 150), ("AppData/Local/cache/browser-cache.bin", 980_000_000, 2),
]
root = os.path.join(tmp, "C_drive")


# Sizes above are scaled down 1000x on disk (GB -> MB) so the demo tree stays
# under 50 MB; sparse files are not reliable across Windows volumes.
SCALE = 1000
for rel, size, age in DEMO:
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.truncate(max(1, size // SCALE))
    t = time.time() - age * 86400
    os.utime(p, (t - random.randint(0, 86400 * 10), t))

# On Windows, show the demo tree as a drive letter (subst) so the picture looks
# like a real drive scan and contains no user name.
scan_root = root
drive_letter = None
if sys.platform == "win32":
    import subprocess
    for letter in "XYZWVU":
        if not os.path.exists(f"{letter}:\\"):
            if subprocess.run(["subst", f"{letter}:", root], capture_output=True).returncode == 0:
                drive_letter, scan_root = letter, f"{letter}:\\"
            break

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from diskoptimizer.app.main_window import MainWindow  # noqa: E402
from diskoptimizer.app.theme import STYLESHEET  # noqa: E402

app = QApplication(sys.argv)
app.setStyleSheet(STYLESHEET)
win = MainWindow(settings_mod.Settings(last_path=scan_root, min_size_mb=0))
win.resize(1440, 900)
win.show()
win._scan_path(scan_root)


def shoot() -> None:
    out = os.path.join(ROOT, "docs", "screenshot.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    win.grab().save(out)
    print("wrote", out)
    app.quit()
    import shutil
    if drive_letter:
        subprocess.run(["subst", f"{drive_letter}:", "/D"], capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)


QTimer.singleShot(3000, shoot)
app.exec()
