#!/usr/bin/env python3
"""Validate mixed-script typography and ordinary unit spacing."""

from __future__ import annotations

import html
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
AUTOCORRECT = ROOT / "node_modules" / ".bin" / "autocorrect"
TARGETS = ("README.md", "mkdocs.yml", "docs")
FILES = [
    ROOT / "README.md",
    ROOT / "mkdocs.yml",
    *sorted((ROOT / "docs").rglob("*.md")),
    *sorted((ROOT / "docs" / "assets" / "figures").glob("*.svg")),
]
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
DISPLAY_MATH = re.compile(r"^\s*\$\$\s*$")
INLINE_CODE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1", re.DOTALL)
INLINE_MATH = re.compile(r"(?<!\\)\$(?!\$)(?:\\.|[^$\n])+?(?<!\\)\$")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
HTML_TAG = re.compile(r"<[^>\n]+>")
RAW_URL = re.compile(r"https?://[^\s<>()]+")
ATTRIBUTE_LIST = re.compile(r"\{(?:[#.][^}\n]+)\}")
MARKDOWN_LINK = re.compile(
    r"(?P<image>!?)\[(?P<label>[^\]]+)\]"
    r"\((?:[^()]|\([^)]*\))*\)"
)
CJK = r"\u3400-\u9fff\uf900-\ufaff"
MIXED_SCRIPT = re.compile(
    rf"(?:[{CJK}][A-Za-z0-9]|[A-Za-z0-9][{CJK}])"
)
SPACE_BEFORE_FULLWIDTH = re.compile(
    rf"(?<=[{CJK}A-Za-z0-9])[ \t]+(?=[，。！？；：、）》】」』])"
)
SPACE_AFTER_FULLWIDTH = re.compile(
    rf"(?<=[，。！？；：、）》】」』])[ \t]+(?=[{CJK}A-Za-z0-9])"
)
SPACE_AFTER_FULLWIDTH_OPEN = re.compile(
    rf"(?<=[（《【「『])[ \t]+(?=[{CJK}A-Za-z0-9])"
)
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?"
UNITS = (
    "TFLOP/s",
    "GFLOP/s",
    "MFLOP/s",
    "requests/s",
    "request/s",
    "packets/s",
    "packet/s",
    "operations/s",
    "operation/s",
    "TiB/s",
    "GiB/s",
    "MiB/s",
    "KiB/s",
    "TB/s",
    "GB/s",
    "MB/s",
    "KB/s",
    "B/s",
    "Tbps",
    "Gbps",
    "Mbps",
    "Kbps",
    "FLOPS",
    "TFLOP",
    "GFLOP",
    "MFLOP",
    "IOPS",
    "QPS",
    "PiB",
    "TiB",
    "GiB",
    "MiB",
    "KiB",
    "PB",
    "TB",
    "GB",
    "MB",
    "KB",
    "kB",
    "bytes",
    "byte",
    "bits",
    "bit",
    "THz",
    "GHz",
    "MHz",
    "kHz",
    "Hz",
    "µs",
    "μs",
    "ns",
    "us",
    "ms",
    "min",
    "km",
    "cm",
    "mm",
    "kg",
    "mg",
    "kW",
    "mW",
    "mV",
    "mA",
    "bps",
    "FLOP",
    "B",
    "s",
    "h",
    "m",
    "g",
    "W",
    "V",
    "A",
)
UNIT = re.compile(
    rf"(?<![A-Za-z0-9_.:/-])(?P<number>{NUMBER})"
    rf"(?P<unit>{'|'.join(map(re.escape, UNITS))})(?![A-Za-z0-9])"
)
SPACED_PERCENT_OR_DEGREE = re.compile(
    rf"(?P<number>{NUMBER})[ \t]+(?P<mark>[%％°])"
)


def mask_range(chars: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if chars[index] != "\n":
            chars[index] = " "


def mask_fences_and_display_math(text: str) -> list[str]:
    chars = list(text)
    offset = 0
    fence_char: str | None = None
    fence_length = 0
    in_display_math = False
    for line in text.splitlines(keepends=True):
        fence = FENCE.match(line)
        if fence_char is not None:
            mask_range(chars, offset, offset + len(line))
            marker = fence.group(1) if fence else ""
            if marker.startswith(fence_char) and len(marker) >= fence_length:
                fence_char = None
                fence_length = 0
            offset += len(line)
            continue
        if fence:
            marker = fence.group(1)
            fence_char = marker[0]
            fence_length = len(marker)
            mask_range(chars, offset, offset + len(line))
            offset += len(line)
            continue
        if in_display_math or DISPLAY_MATH.match(line):
            mask_range(chars, offset, offset + len(line))
            if DISPLAY_MATH.match(line):
                in_display_math = not in_display_math
            offset += len(line)
            continue
        offset += len(line)
    return chars


def semantic_reader_line(line: str) -> str:
    line = HTML_COMMENT.sub("", line)
    line = INLINE_CODE.sub("A", line)
    line = INLINE_MATH.sub("¤", line)
    line = MARKDOWN_LINK.sub(
        lambda match: "" if match.group("image") else match.group("label"),
        line,
    )
    line = HTML_TAG.sub("", line)
    line = RAW_URL.sub("", line)
    line = ATTRIBUTE_LIST.sub("", line)
    line = re.sub(r"(?<!\\)(?:\*\*|__|~~|\*|_)", "", line)
    return html.unescape(line)


def run_autocorrect(errors: list[str]) -> int:
    if not AUTOCORRECT.is_file():
        errors.append("AutoCorrect is unavailable; run `npm ci` first")
        return 0
    result = subprocess.run(
        [
            str(AUTOCORRECT),
            "--lint",
            "--strict",
            "--format",
            "json",
            "--quiet",
            *TARGETS,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if not result.stdout.strip():
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        errors.append(f"AutoCorrect produced no report: {detail}")
        return 0
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        errors.append(f"AutoCorrect returned invalid JSON: {exc}")
        return 0
    issue_count = 0
    for message in report.get("messages", []):
        path = message.get("filepath", "<unknown>")
        if message.get("error"):
            errors.append(f"{path}: {message['error']}")
        for issue in message.get("lines", []):
            issue_count += 1
            old = issue.get("old", "").strip()
            new = issue.get("new", "").strip()
            errors.append(
                f"{path}:{issue.get('l', '?')}:{issue.get('c', '?')}: "
                f"copywriting: {old!r} -> {new!r}"
            )
    if result.returncode not in {0, 1}:
        detail = result.stderr.strip() or "unknown error"
        errors.append(f"AutoCorrect failed with status {result.returncode}: {detail}")
    return issue_count


def check_semantic_typography(errors: list[str]) -> tuple[int, int]:
    boundary_issues = 0
    issue_count = 0
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        visible = "".join(mask_fences_and_display_math(text))
        relative = path.relative_to(ROOT)
        for number, line in enumerate(visible.splitlines(), 1):
            semantic = semantic_reader_line(line)
            if MIXED_SCRIPT.search(semantic):
                boundary_issues += 1
                errors.append(
                    f"{relative}:{number}: add a space at a rendered "
                    "Chinese/English or Chinese/number boundary"
                )
            if (
                SPACE_BEFORE_FULLWIDTH.search(semantic)
                or SPACE_AFTER_FULLWIDTH.search(semantic)
                or SPACE_AFTER_FULLWIDTH_OPEN.search(semantic)
            ):
                boundary_issues += 1
                errors.append(
                    f"{relative}:{number}: remove spacing adjacent to "
                    "full-width punctuation"
                )
            for match in UNIT.finditer(semantic):
                issue_count += 1
                errors.append(
                    f"{relative}:{number}: add a space between "
                    f"{match.group('number')} and {match.group('unit')}"
                )
            for match in SPACED_PERCENT_OR_DEGREE.finditer(semantic):
                issue_count += 1
                errors.append(
                    f"{relative}:{number}: remove the space before "
                    f"{match.group('mark')}"
                )
    return boundary_issues, issue_count


def main() -> None:
    errors: list[str] = []
    autocorrect_issues = run_autocorrect(errors)
    boundary_issues, unit_issues = check_semantic_typography(errors)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        raise SystemExit(1)
    print(
        "Copywriting check passed: "
        f"{len(FILES)} reader-facing sources, "
        f"{autocorrect_issues} mixed-script issues, "
        f"{boundary_issues} rendered-boundary issues, "
        f"{unit_issues} unit-spacing issues"
    )


if __name__ == "__main__":
    main()
