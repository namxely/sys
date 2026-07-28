#!/usr/bin/env python3
"""Validate original SVG diagrams, manifest metadata, and placements."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "docs" / "assets" / "figures"
MANIFEST = FIGURES / "manifest.json"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FORBIDDEN_TAGS = {"script", "foreignObject", "iframe", "object", "embed"}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    value.update(path.read_bytes())
    return value.hexdigest()


errors: list[str] = []
try:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    print(f"{MANIFEST.relative_to(ROOT)}: {error}", file=sys.stderr)
    raise SystemExit(1)

if manifest.get("schema_version") != 1:
    errors.append("figure manifest: schema_version must be 1")
if manifest.get("license") != "MIT":
    errors.append("figure manifest: expected repository MIT license")
assets = manifest.get("assets")
if not isinstance(assets, list):
    errors.append("figure manifest: assets must be a list")
    assets = []

listed: set[Path] = set()
ids: set[str] = set()
for index, asset in enumerate(assets):
    label = f"assets[{index}]"
    required = {
        "id",
        "file",
        "sha256",
        "width",
        "height",
        "placement",
        "sources",
    }
    if not isinstance(asset, dict) or set(asset) != required:
        errors.append(f"{label}: fields must be {', '.join(sorted(required))}")
        continue
    identifier = asset["id"]
    if not isinstance(identifier, str) or not ID.fullmatch(identifier):
        errors.append(f"{label}.id: invalid identifier")
    elif identifier in ids:
        errors.append(f"{label}.id: duplicate {identifier}")
    ids.add(identifier)
    file = FIGURES / asset["file"]
    listed.add(file)
    if file.suffix != ".svg" or not file.is_file():
        errors.append(f"{label}.file: missing SVG {asset['file']}")
        continue
    if not isinstance(asset["sha256"], str) or not SHA256.fullmatch(asset["sha256"]):
        errors.append(f"{label}.sha256: invalid digest")
    elif digest(file) != asset["sha256"]:
        errors.append(f"{label}.sha256: digest mismatch")
    text = file.read_text(encoding="utf-8")
    reference_scan = text.replace(
        'xmlns="http://www.w3.org/2000/svg"',
        "",
    ).replace(
        'xmlns:xlink="http://www.w3.org/1999/xlink"',
        "",
    )
    if re.search(
        r"(?:https?:|javascript:|data:)",
        reference_scan,
        re.IGNORECASE,
    ):
        errors.append(f"{label}.file: embedded external or executable reference")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        errors.append(f"{label}.file: invalid SVG XML: {error}")
        continue
    if local(root.tag) != "svg":
        errors.append(f"{label}.file: root element must be svg")
    if root.attrib.get("width") != str(asset["width"]):
        errors.append(f"{label}.width: does not match SVG")
    if root.attrib.get("height") != str(asset["height"]):
        errors.append(f"{label}.height: does not match SVG")
    titles = [
        "".join(element.itertext()).strip()
        for element in root.iter()
        if local(element.tag) == "title"
    ]
    descriptions = [
        "".join(element.itertext()).strip()
        for element in root.iter()
        if local(element.tag) == "desc"
    ]
    if not any(titles) or not any(descriptions):
        errors.append(f"{label}.file: requires non-empty title and desc")
    for element in root.iter():
        if local(element.tag) in FORBIDDEN_TAGS:
            errors.append(f"{label}.file: forbidden element {local(element.tag)}")
        for name in element.attrib:
            if local(name).lower().startswith("on"):
                errors.append(f"{label}.file: forbidden event attribute {name}")
    sources = asset["sources"]
    if (
        not isinstance(sources, list)
        or len(sources) < 1
        or any(not isinstance(url, str) or not url.startswith("https://") for url in sources)
    ):
        errors.append(f"{label}.sources: require HTTPS source links")
    placement = ROOT / asset["placement"]
    if not placement.is_file():
        errors.append(f"{label}.placement: missing {asset['placement']}")
    else:
        target = f"assets/figures/{asset['file']}"
        if target not in placement.read_text(encoding="utf-8"):
            errors.append(f"{label}.placement: page does not reference {target}")

orphans = set(FIGURES.glob("*.svg")) - listed
for file in sorted(orphans):
    errors.append(f"{file.relative_to(ROOT)}: SVG is not listed in manifest")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print(f"Figure check passed: {len(assets)} original SVG diagrams")
