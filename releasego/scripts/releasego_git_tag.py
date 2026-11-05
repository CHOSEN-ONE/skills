#!/usr/bin/env python3
"""Create or verify a Git tag through the Git protocol, without browser access."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from releasego_config import load_config, work_directory


def run_git(args: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def ls_remote(repo_url: str, pattern: str) -> list[tuple[str, str]]:
    result = run_git(["ls-remote", repo_url, pattern])
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            rows.append((parts[0], parts[1]))
    return rows


def json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or verify a remote Git tag without browser automation.")
    parser.add_argument("--repo-url", required=True)
    parser.add_argument("--tag-name", required=True)
    parser.add_argument("--ref", default="master", help="Source branch/tag/sha to tag. Defaults to master.")
    parser.add_argument("--work-dir", type=lambda value: Path(value).expanduser().resolve(), default=work_directory(load_config()) / "git-tag-work")
    parser.add_argument("--allow-existing-same-target", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--confirm-write", choices=["yes"], help="Required unless --verify-only is set.")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    tag_ref = f"refs/tags/{args.tag_name}"
    existing_tags = ls_remote(args.repo_url, tag_ref)
    source_refs = ls_remote(args.repo_url, args.ref)
    if not source_refs and not args.ref.startswith("refs/"):
        source_refs = ls_remote(args.repo_url, f"refs/heads/{args.ref}") + ls_remote(args.repo_url, f"refs/tags/{args.ref}")

    source_sha = source_refs[0][0] if source_refs else None
    source_remote_ref = source_refs[0][1] if source_refs else None
    output: dict[str, Any] = {
        "repoUrl": args.repo_url,
        "tagName": args.tag_name,
        "ref": args.ref,
        "sourceSha": source_sha,
        "sourceRemoteRef": source_remote_ref,
        "existingTagSha": existing_tags[0][0] if existing_tags else None,
    }

    if args.verify_only:
        output["exists"] = bool(existing_tags)
        json_print(output)
        return 0 if existing_tags else 1

    if args.confirm_write != "yes":
        raise SystemExit("This command creates a remote Git tag. Re-run with --confirm-write yes after verifying all arguments.")
    if not source_sha:
        raise SystemExit(f"Source ref not found: {args.ref}")
    if existing_tags:
        if args.allow_existing_same_target and existing_tags[0][0] == source_sha:
            output["created"] = False
            output["alreadyExists"] = True
            json_print(output)
            return 0
        raise SystemExit(f"Tag already exists: {tag_ref} -> {existing_tags[0][0]}")

    args.work_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="tag-", dir=args.work_dir))
    try:
        run_git(["init"], cwd=tmp)
        run_git(["remote", "add", "origin", args.repo_url], cwd=tmp)
        run_git(["fetch", "--depth", "1", "origin", source_remote_ref or args.ref], cwd=tmp)
        run_git(["tag", args.tag_name, "FETCH_HEAD"], cwd=tmp)
        run_git(["push", "origin", tag_ref], cwd=tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    created_tags = ls_remote(args.repo_url, tag_ref)
    output["created"] = bool(created_tags)
    output["tagSha"] = created_tags[0][0] if created_tags else None
    json_print(output)
    return 0 if created_tags and created_tags[0][0] == source_sha else 1


if __name__ == "__main__":
    sys.exit(main())
