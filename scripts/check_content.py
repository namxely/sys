#!/usr/bin/env python3
"""Validate public Markdown structure, references, and sensitive patterns."""

from __future__ import annotations

from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
FILES = [ROOT / "README.md", *sorted(DOCS.rglob("*.md"))]
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
H2 = re.compile(r"^##\s+(.+?)\s*$")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
REFERENCE = re.compile(r"^##\s+Reference\s*$")
PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b|待补充|稍后补充")
SECRET_PATTERNS = {
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "macOS home path": re.compile(r"/Users/[^/\s]+/"),
    "Windows home path": re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\"),
}
GENERIC_LINK_TEXT = {
    "here",
    "link",
    "source",
    "docs",
    "paper",
    "点击",
    "这里",
    "点击这里",
}
EXEMPT = {
    Path("index.md"),
    Path("glossary.md"),
    Path("resources.md"),
    Path("changelog.md"),
}


def is_exempt(path: Path) -> bool:
    relative = path.relative_to(DOCS)
    return relative in EXEMPT or relative.name == "index.md"


def visible_size(text: str) -> int:
    without_fences = re.sub(r"(?ms)^(`{3,}|~{3,}).*?^\1\s*$", "", text)
    without_links = LINK.sub(lambda match: match.group(1), without_fences)
    return len(re.sub(r"\s+", "", without_links))


errors: list[str] = []
substantive = 0
reference_pages = 0
reference_links = 0

for path in FILES:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    relative = path.relative_to(ROOT)
    open_fence: tuple[str, int] | None = None
    headings: list[tuple[int, str]] = []
    for number, line in enumerate(lines, 1):
        match = FENCE.match(line)
        if match:
            marker = match.group(1)
            if open_fence is None:
                open_fence = (marker[0], number)
            elif marker[0] == open_fence[0]:
                open_fence = None
        if open_fence is None:
            heading = H2.match(line)
            if heading:
                headings.append((number, heading.group(1).strip()))
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(line):
                errors.append(f"{relative}:{number}: detected {name} pattern")
        if open_fence is None:
            prose = re.sub(r"`[^`]*`", "", line)
            if PLACEHOLDER.search(prose):
                errors.append(f"{relative}:{number}: unresolved placeholder")
            prose = re.sub(r"\]\(https?://[^)]+\)", "]()", prose)
            prose = re.sub(
                r"""(?:href|src)\s*=\s*["']https?://[^"']+["']""",
                "",
                prose,
                flags=re.IGNORECASE,
            )
            if re.search(r"https?://", prose):
                errors.append(f"{relative}:{number}: bare URL; use a descriptive link")
    if open_fence:
        errors.append(f"{relative}:{open_fence[1]}: unclosed fenced code block")
    if path == ROOT / "README.md":
        continue
    minimum = 300 if path.relative_to(DOCS) == Path("changelog.md") else (
        450 if is_exempt(path) else 1200
    )
    if visible_size(text) < minimum:
        errors.append(f"{relative}: page is too thin for its role")
    if is_exempt(path):
        continue
    substantive += 1
    reference_lines = [
        number for number, heading in headings if heading == "Reference"
    ]
    if len(reference_lines) != 1:
        errors.append(f"{relative}: expected exactly one H2 Reference section")
        continue
    reference_pages += 1
    if headings[-1][1] != "Reference":
        errors.append(f"{relative}: Reference must be the final H2 section")
    start = reference_lines[0]
    destinations: set[str] = set()
    page_reference_links = 0
    for number, line in enumerate(lines[start:], start + 1):
        for label, destination in LINK.findall(line):
            parsed = urlsplit(destination)
            if parsed.scheme not in {"http", "https"}:
                continue
            if parsed.scheme != "https":
                errors.append(f"{relative}:{number}: external references require HTTPS")
            normalized = destination.rstrip("/")
            if normalized in destinations:
                errors.append(f"{relative}:{number}: duplicate Reference destination")
            destinations.add(normalized)
            if label.strip().lower() in GENERIC_LINK_TEXT:
                errors.append(f"{relative}:{number}: non-descriptive Reference label")
            page_reference_links += 1
    if page_reference_links < 3:
        errors.append(f"{relative}: substantive page needs at least 3 references")
    reference_links += page_reference_links

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print(
    "Content check passed: "
    f"{len(FILES)} Markdown files, {substantive} substantive pages, "
    f"{reference_pages} Reference sections, {reference_links} reference links"
)
