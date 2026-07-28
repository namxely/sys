#!/usr/bin/env python3
"""Parse and compile complete teaching snippets with available toolchains."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FILES = sorted((ROOT / "docs").rglob("*.md"))
OPEN = re.compile(r"^```([A-Za-z0-9_+.-]+)(?:\s+.*)?$")
LANGUAGE = {
    "py": "python",
    "python": "python",
    "c": "c",
    "cpp": "cpp",
    "c++": "cpp",
    "cc": "cpp",
    "cuda": "cuda",
    "cu": "cuda",
    "go": "go",
    "rust": "rust",
    "rs": "rust",
    "java": "java",
    "javascript": "javascript",
    "js": "javascript",
    "typescript": "typescript",
    "ts": "typescript",
}


def run(command: list[str], cwd: Path) -> str | None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode:
        return (completed.stderr or completed.stdout).strip()
    return None


snippets: list[tuple[Path, int, str, str]] = []
for path in FILES:
    lines = path.read_text(encoding="utf-8").splitlines()
    active: tuple[str, int] | None = None
    block: list[str] = []
    for number, line in enumerate(lines, 1):
        if active is None:
            match = OPEN.match(line)
            if match and match.group(1).lower() in LANGUAGE:
                active = (LANGUAGE[match.group(1).lower()], number)
                block = []
        elif line == "```":
            snippets.append((path, active[1], active[0], "\n".join(block) + "\n"))
            active = None
            block = []
        else:
            block.append(line)

errors: list[str] = []
counts: dict[str, int] = {}
compiled: dict[str, int] = {}
for path, line, language, source in snippets:
    counts[language] = counts.get(language, 0) + 1
    label = f"{path.relative_to(ROOT)}:{line}"
    if language == "python":
        try:
            ast.parse(source)
        except SyntaxError as error:
            errors.append(f"{label}:{error.lineno}: {error.msg}")
        else:
            compiled[language] = compiled.get(language, 0) + 1
        continue
    with tempfile.TemporaryDirectory(prefix="sys-snippet-") as raw:
        directory = Path(raw)
        command: list[str] | None = None
        if (
            language == "c"
            and re.search(r"\bmain\s*\(", source)
            and not (
                sys.platform != "linux"
                and re.search(
                    r"#\s*include\s*<(?:sched\.h|sys/(?:epoll|eventfd|timerfd)\.h)>",
                    source,
                )
            )
        ):
            if shutil.which("cc"):
                file = directory / "snippet.c"
                file.write_text(source, encoding="utf-8")
                command = ["cc", "-std=c17", "-Wall", "-Wextra", "-Werror", "-fsyntax-only", str(file)]
        elif language == "cpp" and re.search(r"\bmain\s*\(", source):
            if shutil.which("c++"):
                file = directory / "snippet.cpp"
                file.write_text(source, encoding="utf-8")
                command = ["c++", "-std=c++23", "-Wall", "-Wextra", "-Werror", "-pthread", "-fsyntax-only", str(file)]
        elif language == "cuda" and re.search(r"\bmain\s*\(", source):
            if shutil.which("nvcc"):
                file = directory / "snippet.cu"
                file.write_text(source, encoding="utf-8")
                command = [
                    "nvcc",
                    "-std=c++17",
                    "-c",
                    str(file),
                    "-o",
                    str(directory / "snippet.o"),
                ]
            elif os.environ.get("CI"):
                errors.append(f"{label}: complete CUDA example requires nvcc in CI")
                continue
        elif language == "go" and re.search(r"(?m)^\s*package\s+main\b", source):
            if shutil.which("go"):
                file = directory / "main.go"
                file.write_text(source, encoding="utf-8")
                command = ["go", "test", "."]
                (directory / "go.mod").write_text("module snippet\n\ngo 1.23\n", encoding="utf-8")
        elif language == "rust" and re.search(r"\bfn\s+main\s*\(", source):
            if shutil.which("rustc"):
                file = directory / "main.rs"
                file.write_text(source, encoding="utf-8")
                command = ["rustc", "--edition=2021", "--emit=metadata", str(file)]
        elif language == "java" and re.search(
            r"\bpublic\s+(?:final\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)",
            source,
        ):
            javac = shutil.which("javac")
            if javac and run([javac, "-version"], directory) is None:
                class_name = re.search(
                    r"\bpublic\s+(?:final\s+)?class\s+"
                    r"([A-Za-z_$][A-Za-z0-9_$]*)",
                    source,
                )
                assert class_name is not None
                file = directory / f"{class_name.group(1)}.java"
                file.write_text(source, encoding="utf-8")
                command = [
                    javac,
                    "--release",
                    "25",
                    "-Xlint:all",
                    "-Werror",
                    str(file),
                ]
        elif language == "javascript":
            if shutil.which("node"):
                file = directory / "snippet.mjs"
                file.write_text(source, encoding="utf-8")
                command = ["node", "--check", str(file)]
        elif language == "typescript":
            local_tsc = ROOT / "node_modules" / ".bin" / "tsc"
            tsc = str(local_tsc) if local_tsc.is_file() else shutil.which("tsc")
            if tsc:
                file = directory / "snippet.ts"
                file.write_text(source, encoding="utf-8")
                command = [
                    tsc,
                    "--noEmit",
                    "--strict",
                    "--target",
                    "ES2022",
                    "--module",
                    "NodeNext",
                    "--moduleResolution",
                    "NodeNext",
                    "--skipLibCheck",
                    str(file),
                ]
        if command is None:
            continue
        failure = run(command, directory)
        if failure:
            errors.append(f"{label}: {language} check failed\n{failure}")
        else:
            compiled[language] = compiled.get(language, 0) + 1

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print(
    f"Code check passed: {len(snippets)} fenced snippets; "
    + ", ".join(
        f"{name} {compiled.get(name, 0)}/{count}"
        for name, count in sorted(counts.items())
    )
)
