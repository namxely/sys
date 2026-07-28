#!/usr/bin/env python3
"""Validate MkDocs navigation coverage and source-level internal links."""

from __future__ import annotations

from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CONFIG = ROOT / "mkdocs.yml"
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
REQUIRED_ROOTS = {
    "foundations",
    "architecture",
    "os",
    "concurrency",
    "network",
    "storage",
    "parallel",
    "distributed",
    "languages",
    "tooling",
    "performance",
}


def nav_paths(value: object) -> list[str]:
    result: list[str] = []
    if isinstance(value, str):
        if value.endswith(".md"):
            result.append(value)
    elif isinstance(value, list):
        for item in value:
            result.extend(nav_paths(item))
    elif isinstance(value, dict):
        for item in value.values():
            result.extend(nav_paths(item))
    return result


config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
listed = nav_paths(config.get("nav", []))
errors: list[str] = []
if len(listed) != len(set(listed)):
    duplicates = sorted({item for item in listed if listed.count(item) > 1})
    errors.append(f"mkdocs.yml: duplicate nav pages: {', '.join(duplicates)}")

existing = {
    path.relative_to(DOCS).as_posix() for path in DOCS.rglob("*.md")
}
listed_set = set(listed)
for item in sorted(listed_set - existing):
    errors.append(f"mkdocs.yml: nav target does not exist: {item}")
for item in sorted(existing - listed_set):
    errors.append(f"docs/{item}: page is not reachable from nav")

present_roots = {Path(item).parts[0] for item in existing if "/" in item}
missing_roots = sorted(REQUIRED_ROOTS - present_roots)
if missing_roots:
    errors.append(f"missing canonical areas: {', '.join(missing_roots)}")

link_count = 0
for relative in sorted(existing):
    path = DOCS / relative
    lines = path.read_text(encoding="utf-8").splitlines()
    active_fence: str | None = None
    for number, line in enumerate(lines, 1):
        marker = FENCE.match(line)
        if marker:
            char = marker.group(1)[0]
            active_fence = None if active_fence == char else char
            continue
        if active_fence:
            continue
        for destination in LINK.findall(line):
            parsed = urlsplit(destination)
            if parsed.scheme or parsed.netloc or destination.startswith("#"):
                continue
            if not parsed.path:
                continue
            target = (path.parent / unquote(parsed.path)).resolve()
            if target.suffix == "":
                target = target / "index.md"
            if target.suffix.lower() != ".md":
                continue
            link_count += 1
            try:
                target.relative_to(DOCS.resolve())
            except ValueError:
                errors.append(
                    f"docs/{relative}:{number}: internal link escapes docs: {destination}"
                )
                continue
            if not target.exists():
                errors.append(
                    f"docs/{relative}:{number}: missing internal target: {destination}"
                )

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print(
    f"Architecture check passed: {len(existing)} pages, "
    f"{len(listed_set)} nav entries, {link_count} source links"
)
