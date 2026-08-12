#!/usr/bin/env python3
"""Reject browser remnants, session artifacts, and obvious text corruption in this skill."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".py", ".yaml", ".yml"}
FORBIDDEN_SCRIPT_TEXT = (
    "agent-" + "browser",
    "chrome-" + "remote-9222",
    "--" + "cdp",
    "ui " + "automation",
    "browser " + "cookies",
)
FORBIDDEN_FILES = {
    "chandao" + "-state.json",
    "raw-" + "auth.json",
    "chandao-" + "http-cookies.txt",
}
FORBIDDEN_SUFFIXES = {".cmd", ".mjs", ".ps1", ".pyc"}
MOJIBAKE_MARKERS = ("\ufffd", "\u93ae\u86e7", "\u6d93\u7ade")


def main() -> int:
    problems: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if "__pycache__" in relative.parts:
            problems.append(f"compiled Python artifact: {relative}")
            continue
        if path.name in FORBIDDEN_FILES:
            problems.append(f"session artifact: {relative}")
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            problems.append(f"browser or compiled artifact: {relative}")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"not valid UTF-8: {relative}")
            continue
        lowered = content.lower()
        if relative.parent == Path("scripts") and relative != Path("scripts/check_text_integrity.py"):
            for term in FORBIDDEN_SCRIPT_TEXT:
                if term in lowered:
                    problems.append(f"browser remnant {term!r}: {relative}")
        for marker in MOJIBAKE_MARKERS:
            if marker in content:
                problems.append(f"text corruption marker: {relative}")
    if problems:
        print("Text integrity check failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print("Text integrity check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
