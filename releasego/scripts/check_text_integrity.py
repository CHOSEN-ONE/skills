#!/usr/bin/env python3
"""Fail if skill text contains common mojibake or invalid Unicode markers."""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path


TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".yaml",
    ".yml",
    ".json",
    ".txt",
}


def token(*codepoints: int) -> str:
    return "".join(chr(codepoint) for codepoint in codepoints)


SUSPICIOUS_TOKENS = [
    token(0xFFFD),
    token(0x003F, 0x003F),
    token(0x951F, 0x65A4, 0x62F7),
    token(0x93AE, 0x71BA, 0x2516),
    token(0x7459, 0x5099, 0x7C2F),
    token(0x9359, 0x6220, 0x5897),
    token(0x7EEF, 0x8364, 0x7CBA),
    token(0x7EC9, 0x4F79, 0x6E41),
    token(0x9356, 0x6827, 0x5F42),
    token(0x7EDB, 0x590A, 0x7DDF),
    token(0x95C6, 0x55D8, 0x579A),
    token(0x5BB8, 0x832C, 0x7CA1),
    token(0x9359, 0x5099, 0x7B0C),
    token(0x9359, 0x6A3B, 0x6D3F),
    token(0x6434, 0x65C2, 0x6564),
    token(0x95B0, 0x5D87, 0x7586),
    token(0x9427, 0x8BF2, 0x7D8D),
    token(0x9369, 0x8F70, 0x7C2C),
    token(0x5BB8, 0x63D2, 0x5F42),
    token(0x93CD, 0x89C4, 0x5D41),
    token(0x947E, 0x5CF0, 0x5F47),
    token(0x5A11, 0x590A, 0x5F37),
    token(0x95B9),
    token(0x95B8),
    token(0x941F),
    token(0x7F01, 0x6D98),
    token(0x7039, 0x6B4C),
    token(0x93C2, 0x677F),
    token(0x9864),
    token(0x7ED4, 0x5B2A),
    token(0x9352, 0x55D7),
    token(0x9417, 0x581F),
    token(0x9418, 0x8235),
    token(0x934F, 0x3129),
]


def iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.resolve() == Path(__file__).resolve():
            continue
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            files.append(path)
    return sorted(files)


def check_file(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return [f"{path}: not valid UTF-8: {exc}"]

    for lineno, line in enumerate(text.splitlines(), 1):
        for suspicious in SUSPICIOUS_TOKENS:
            if suspicious in line:
                problems.append(f"{path}:{lineno}: suspicious mojibake token found: {line}")
                break
        else:
            private_chars = [ch for ch in line if unicodedata.category(ch) == "Co"]
            if private_chars:
                unique = "".join(dict.fromkeys(private_chars))
                problems.append(f"{path}:{lineno}: private-use Unicode {unique!r}: {line}")
    return problems



def check_packaging_safety(root: Path) -> list[str]:
    problems: list[str] = []
    local_config = root / "config.local.json"
    if local_config.exists():
        problems.append(f"{local_config}: local credential config must not exist in the skill source before packaging")
    for cache_dir in sorted(path for path in root.rglob("__pycache__") if path.is_dir()):
        problems.append(f"{cache_dir}: Python bytecode cache must not exist in the skill source before packaging")
    return problems


def check_package_file(package_path: Path) -> list[str]:
    import zipfile

    problems: list[str] = []
    if not package_path.exists():
        return [f"{package_path}: package file does not exist"]
    with zipfile.ZipFile(package_path) as zipf:
        for name in zipf.namelist():
            normalized = name.replace("\\", "/")
            if normalized.endswith("/config.local.json") or normalized == "config.local.json":
                problems.append(f"{package_path}: package contains forbidden local credential file {name}")
            if "__pycache__" in normalized.split("/") or normalized.endswith(".pyc"):
                problems.append(f"{package_path}: package contains forbidden Python bytecode cache {name}")
    return problems

def main() -> int:
    parser = argparse.ArgumentParser(description="Check releasego skill files for mojibake and invalid Unicode.")
    parser.add_argument("root", nargs="?", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument("--package", type=Path, help="Optional .skill package to inspect for forbidden local credential files.")
    args = parser.parse_args()

    root = args.root.resolve()
    problems: list[str] = []
    problems.extend(check_packaging_safety(root))
    for path in iter_text_files(root):
        problems.extend(check_file(path))
    if args.package:
        problems.extend(check_package_file(args.package.resolve()))

    if problems:
        print("Text integrity check failed:", file=sys.stderr)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1

    print(f"Text integrity OK: {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
