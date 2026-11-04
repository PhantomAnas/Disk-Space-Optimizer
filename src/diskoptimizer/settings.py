"""App settings and their JSON persistence (platformdirs config folder)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields

from platformdirs import user_config_dir

APP_NAME = "DiskSpaceOptimizer"


def config_path() -> str:
    return os.path.join(user_config_dir(APP_NAME, appauthor=False), "settings.json")


def log_path() -> str:
    return os.path.join(user_config_dir(APP_NAME, appauthor=False), "trash-log.jsonl")


@dataclass
class Settings:
    last_path: str = ""
    top_n: int = 500
    min_size_mb: float = 1.0
    older_than_days: int = 0
    categories: list = field(default_factory=list)      # empty = all
    sort_column: str = "size"
    sort_descending: bool = True
    find_duplicates: bool = False
    extra: dict = field(default_factory=dict)

    def validate(self) -> list[str]:
        problems = []
        if not 1 <= self.top_n <= 100000:
            problems.append("top N must be between 1 and 100000")
        if self.min_size_mb < 0:
            problems.append("minimum size cannot be negative")
        if self.older_than_days < 0:
            problems.append("older-than days cannot be negative")
        return problems

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        try:
            return cls(**clean)
        except TypeError:
            return cls()

    @classmethod
    def load(cls, path: str | None = None) -> "Settings":
        path = path or config_path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return cls()
        return cls.from_dict(data) if isinstance(data, dict) else cls()

    def save(self, path: str | None = None) -> None:
        path = path or config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)
        os.replace(tmp, path)
