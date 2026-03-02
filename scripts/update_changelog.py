#!/usr/bin/env python3
# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
update_changelog.py — Prepend a version section to CHANGELOG.md based on commit
subjects since last tag.

Usage:
  python scripts/update_changelog.py <VERSION>
"""
from __future__ import annotations
import subprocess, sys, datetime, pathlib, re, os

def sh(*args: str, stderr: int | None = None) -> str:
    out = subprocess.check_output(args, text=True, stderr=stderr).strip()
    return out

def main() -> int:
    if len(sys.argv) < 2:
        print("usage: update_changelog.py <VERSION>", file=sys.stderr)
        return 2
    version = sys.argv[1]

    # last tag, if any
    try:
        last_tag = sh("git", "describe", "--tags", "--abbrev=0", stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        # Fallback: newest tag by creation date (may be unrelated if history diverged)
        try:
            tags = sh("git", "for-each-ref", "--sort=-creatordate",
                      "--format=%(refname:short)", "refs/tags", stderr=subprocess.DEVNULL)
            last_tag = tags.splitlines()[0].strip() if tags else ""
        except subprocess.CalledProcessError:
            last_tag = ""

    if last_tag:
        log = sh("git", "log", "--reverse", "--format=%s", f"{last_tag}..HEAD")
    else:
        log = sh("git", "log", "--reverse", "--format=%s")

    lines = [l.strip() for l in log.splitlines() if l.strip()]

    # Keep only lines that start with [tag]; skip chore: and other non-matching formats.
    tag_pat = re.compile(r"^\[([^\]]+)\]")
    chore_pat = re.compile(r"^chore(?:\([^)]+\))?\s*:?\s*(.*)$", re.IGNORECASE)
    norm_map = {
        "api": "API",
        "buid": "Build",
        "build": "Build",
        "bite": "Bite-sized tasks",
        "doc": "Documentation",
        "docs": "Documentation",
        "conf": "Config",
        "core": "Core",
        "store": "Store",
        "infra": "Infrastructure",
        "pkg": "Packaging",
        "ui": "UI",
        "fix": "Bug Fixes",
        "perf": "Performance",
        "performance": "Performance",
        "test": "Testing",
        "cli": "CLI",
    }
    merge_map = {
        "bench": "performance",
    }
    groups: dict[str, list[str]] = {}
    chores: list[str] = []
    titles: dict[str, str] = {}
    seen_groups: set[str] = set()
    seen_chores: set[str] = set()
    for line in lines:
        low = line.lower()
        if low.startswith("chore(release"):
            continue
        if low.startswith("chore:") or low.startswith("chore("):
            m = chore_pat.match(line)
            msg = m.group(1).strip() if m else line
            if msg:
                if len(msg) > 80:
                    msg = msg[:77].rstrip() + "..."
                msg = msg[:1].upper() + msg[1:] if msg else msg
                if msg.lower() not in seen_chores:
                    chores.append(msg)
                    seen_chores.add(msg.lower())
            continue
        if not line.startswith("["):
            continue
        tags = tag_pat.findall(line)
        if not tags:
            continue
        grp = tags[0].strip()
        key = grp.lower()
        key = merge_map.get(key, key)
        grp = norm_map.get(key, grp)
        if grp == grp.lower():
            grp = grp[:1].upper() + grp[1:] if grp else grp
        grp_key = grp.lower()
        if grp_key not in titles:
            titles[grp_key] = grp
        remainder = line
        # Strip the first tag only; keep any secondary tags in the bullet.
        remainder = tag_pat.sub("", remainder, count=1).lstrip()
        if not remainder:
            continue
        # Crop to 80 chars total; if longer, crop at 77 and add "..."
        if len(remainder) > 80:
            remainder = remainder[:77].rstrip() + "..."
        # Capitalize first letter of the commit line
        if remainder:
            remainder = remainder[:1].upper() + remainder[1:]
        key = f"{grp_key}::{remainder.lower()}"
        if key in seen_groups:
            continue
        seen_groups.add(key)
        groups.setdefault(grp_key, []).append(remainder)

    # Sort groups by size (desc), then name (asc). Entries remain in commit order.
    sorted_groups = sorted(
        groups.items(),
        key=lambda kv: (-len(kv[1]), titles[kv[0]].lower())
    )

    today = datetime.date.today().isoformat()
    header = f"## {version} — {today}\n"
    body_lines: list[str] = []
    for grp_key, msgs in sorted_groups:
        title = titles.get(grp_key, grp_key)
        body_lines.append(f"\n### {title}")
        for msg in msgs:
            body_lines.append(f"- {msg}")
    if chores:
        body_lines.append("\n### Chores")
        for msg in chores:
            body_lines.append(f"- {msg}")
    body = "\n".join(body_lines).lstrip("\n") + "\n"
    sep = "\n---\n"

    path = pathlib.Path(
        os.environ.get("CHANGELOG_PATH", "CHANGELOG.md")
    )
    prev = path.read_text(encoding="utf-8") if path.exists() else ""

    # Insert after initial comment header (lines starting with <!-- ... -->).
    lines_prev = prev.splitlines()

    # If an entry for this version (or related rc/final variants) already exists,
    # remove it before inserting the new block. Keep distinct dotted patchlines
    # like X.Y.Z.W as separate versions.
    def _version_base(v: str) -> str:
        m = re.match(r"^(\d+\.\d+\.\d+)(?!\.\d)(.*)$", v)
        return m.group(1) if m else v

    base = _version_base(version)
    block_start = None
    i = 0
    while i < len(lines_prev):
        line = lines_prev[i]
        if line.startswith("## "):
            m = re.match(r"^##\s+([0-9A-Za-z\.\-]+)\s+—", line)
            ver = m.group(1) if m else ""
            if ver and _version_base(ver) == base:
                block_start = i
                j = i + 1
                while j < len(lines_prev):
                    if lines_prev[j].strip() == "---":
                        j += 1
                        break
                    j += 1
                del lines_prev[i:j]
                continue
        i += 1

    insert_at = 0
    while insert_at < len(lines_prev) and lines_prev[insert_at].lstrip().startswith("<!--"):
        insert_at += 1
    # Preserve a single blank line after header block if present.
    if insert_at < len(lines_prev) and lines_prev[insert_at].strip() == "":
        insert_at += 1
    # Avoid duplicate separators if the next line is already a separator.
    next_is_sep = insert_at < len(lines_prev) and lines_prev[insert_at].strip() == "---"
    new_entry = header + "\n" + body + ("" if next_is_sep else sep)
    if prev:
        lines_prev.insert(insert_at, new_entry.rstrip("\n"))
        out = "\n".join(lines_prev).rstrip() + "\n"
    else:
        out = new_entry
    path.write_text(out, encoding="utf-8")

    if os.environ.get("CHANGELOG_SILENT", "").strip().lower() not in {"1", "true", "yes"}:
        print(f"{path.name} updated for {version}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
