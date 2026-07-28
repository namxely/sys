#!/usr/bin/env python3
"""Validate rendered article links, routes, and fragments."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
import posixpath
import sys
from urllib.parse import unquote, urljoin, urlsplit


SITE_PREFIX = "/sys/"


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.article_depth = 0
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.images: list[str] = []

    @staticmethod
    def classes(attrs: list[tuple[str, str | None]]) -> list[str]:
        return (dict(attrs).get("class") or "").split()

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "article" and "md-content__inner" in self.classes(attrs):
            self.article_depth += 1
        identifier = attributes.get("id")
        if identifier:
            self.ids.add(unquote(identifier))
        if self.article_depth and tag == "a":
            href = attributes.get("href")
            if href is not None:
                self.links.append(href)
        if self.article_depth and tag == "img":
            source = attributes.get("src")
            if source:
                self.images.append(source)

    def handle_endtag(self, tag: str) -> None:
        if tag == "article" and self.article_depth:
            self.article_depth -= 1


def route_for(path: Path, site_dir: Path) -> str:
    relative = path.relative_to(site_dir)
    if relative == Path("index.html"):
        return "/"
    return "/" + relative.parent.as_posix().strip("/") + "/"


def normalize_route(source_route: str, href: str) -> tuple[str, str]:
    parsed = urlsplit(href)
    route = unquote(parsed.path)
    if route.startswith(SITE_PREFIX):
        route = "/" + route[len(SITE_PREFIX) :]
    elif not route.startswith("/"):
        route = urlsplit(urljoin("https://local" + source_route, route)).path
    route = posixpath.normpath(route)
    if href.endswith("/") and route != "/":
        route += "/"
    if route.endswith("/index.html"):
        route = route[: -len("index.html")]
    elif route.endswith(".html"):
        route = route[: -len(".html")] + "/"
    if not route.endswith("/") and PurePosixPath(route).suffix == "":
        route += "/"
    return route or "/", unquote(parsed.fragment)


parser = argparse.ArgumentParser()
parser.add_argument("--site-dir", type=Path, default=Path("site"))
args = parser.parse_args()
site_dir = args.site_dir.resolve()
errors: list[str] = []
pages: dict[str, tuple[Path, PageParser]] = {}
assets = {
    "/" + path.relative_to(site_dir).as_posix()
    for path in site_dir.rglob("*")
    if path.is_file()
}

for path in sorted(site_dir.glob("**/index.html")):
    parsed = PageParser()
    parsed.feed(path.read_text(encoding="utf-8"))
    route = route_for(path, site_dir)
    pages[route] = (path, parsed)

checked = 0
for source_route, (path, parsed) in pages.items():
    for href in parsed.links:
        target = urlsplit(href)
        if target.scheme in {"http", "https", "mailto"} or href.startswith("//"):
            continue
        route, fragment = normalize_route(source_route, href)
        if PurePosixPath(route).suffix:
            asset = route
            if asset.startswith(SITE_PREFIX):
                asset = "/" + asset[len(SITE_PREFIX) :]
            if asset not in assets:
                errors.append(f"{path.relative_to(site_dir)}: missing asset {href}")
            checked += 1
            continue
        destination = pages.get(route)
        if destination is None:
            errors.append(f"{path.relative_to(site_dir)}: missing route {href}")
            continue
        if fragment and fragment not in destination[1].ids:
            errors.append(
                f"{path.relative_to(site_dir)}: missing fragment {href}"
            )
        checked += 1
    for source in parsed.images:
        target = urlsplit(source)
        if target.scheme or target.netloc:
            continue
        route, _ = normalize_route(source_route, source)
        if route not in assets:
            errors.append(f"{path.relative_to(site_dir)}: broken image {source}")
        checked += 1

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print(f"Rendered link check passed: {len(pages)} pages, {checked} links/assets")
