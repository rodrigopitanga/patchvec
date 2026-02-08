#!/usr/bin/env python3
# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

"""
update_changelog.py — Prepend a version section to CHANGELOG.md based on commit subjects since last tag.

Usage:
  python scripts/update_changelog.py 0.5.4
"""
from __future__ import annotations
import subprocess, sys, datetime, pathlib

def sh(*args: str) -> str:
    out = subprocess.check_output(args, text=True).strip()
    return out

def main() -> int:
    if len(sys.argv) < 2:
        print("usage: update_changelog.py <VERSION>", file=sys.stderr)
        return 2
    version = sys.argv[1]

    # last tag, if any
    try:
        last_tag = sh("git", "describe", "--tags", "--abbrev=0")
    except subprocess.CalledProcessError:
        last_tag = ""

    if last_tag:
        log = sh("git", "log", "--format=%s", f"{last_tag}..HEAD")
    else:
        log = sh("git", "log", "--format=%s")

    lines = [l.strip() for l in log.splitlines() if l.strip()]
    # unique, case-insensitive sort
    seen, uniq = set(), []
    for l in lines:
        k = l.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(l)
    uniq.sort(key=str.lower)

    today = datetime.date.today().isoformat()
    header = f"## {version} — {today}\n\n### Commits\n"
    body = "".join(f"- {l}\n" for l in uniq)
    sep = "\n---\n"

    path = pathlib.Path("CHANGELOG.md")
    prev = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(header + body + sep + prev, encoding="utf-8")

    print(f"CHANGELOG.md updated for {version}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
