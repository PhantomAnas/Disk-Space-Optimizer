"""Command line: `disk-space-optimizer --cli PATH [--top N] [--category Videos] ...`
Scans and prints; it never deletes anything."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

from . import scanner
from .scanner import CATEGORY_NAMES, Filter, human_size, list_drives


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="disk-space-optimizer --cli", description="List the largest files in a folder or drive.")
    p.add_argument("path", nargs="?", help="folder or drive to scan (omit with --drives)")
    p.add_argument("--top", type=int, default=25, help="how many files to show (default 25)")
    p.add_argument("--category", action="append", choices=CATEGORY_NAMES, help="only these categories (repeatable)")
    p.add_argument("--min-size", type=float, default=0.0, metavar="MB")
    p.add_argument("--older-than", type=int, default=0, metavar="DAYS", help="modified more than DAYS ago")
    p.add_argument("--search", default="", help="only paths containing this text")
    p.add_argument("--sort", choices=sorted(scanner.SORT_KEYS), default="size")
    p.add_argument("--folders", action="store_true", help="also print the biggest top-level folders")
    p.add_argument("--duplicates", action="store_true", help="also list duplicate files among the results")
    p.add_argument("--drives", action="store_true", help="list drives with free space and exit")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if a.drives:
        for d in list_drives():
            print(f"{d.path:6} {d.label:20} {human_size(d.used):>10} used of {human_size(d.total):>10}  ({human_size(d.free)} free)")
        return 0
    if not a.path:
        print("error: give a PATH to scan (or --drives)", file=sys.stderr)
        return 2
    if not os.path.isdir(a.path):
        print(f"error: not a folder: {a.path}", file=sys.stderr)
        return 2
    last = [0.0]

    def progress(files, nbytes, folder):
        print(f"\r  {files:,} files, {human_size(nbytes)} ...", end="", flush=True)

    try:
        res = scanner.scan(a.path, top_n=max(a.top, 500), progress=progress)
    except OSError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    print(f"\r{res.total_files:,} files, {human_size(res.total_bytes)} in {res.root} "
          f"({res.seconds:.1f}s, {res.skipped} unreadable, {res.system_hidden} Windows/system items hidden)")
    flt = Filter(categories=set(a.category) if a.category else None, text=a.search,
                 min_size=int(a.min_size * 1024 * 1024), older_than_days=a.older_than)
    rows = scanner.apply(res.files, flt, a.sort, descending=a.sort in ("size", "modified", "accessed"))[: a.top]
    print(f"\n{'size':>10}  {'modified':10}  {'category':14} path")
    for f in rows:
        print(f"{human_size(f.size):>10}  {dt.date.fromtimestamp(f.mtime)}  {f.category:14} {f.path}")
    if a.folders:
        print("\nBiggest folders:")
        for node in res.tree.sorted_children()[:15]:
            print(f"{human_size(node.size):>10}  {node.path}")
    if a.duplicates:
        groups = scanner.find_duplicates(res.files)
        print(f"\n{len(groups)} duplicate group(s)")
        for g in groups[:20]:
            print(f"  {human_size(g[0].size)} x{len(g)}: " + " | ".join(f.path for f in g))
    return 0


if __name__ == "__main__":
    sys.exit(main())
