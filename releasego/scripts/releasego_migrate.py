#!/usr/bin/env python3
"""Apply selected ReleaseGo commits or patches to a local branch without committing."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


class CommandError(Exception):
    def __init__(self, command: str, code: int, stdout: str, stderr: str) -> None:
        super().__init__(command)
        self.command = command
        self.code = code
        self.stdout = stdout
        self.stderr = stderr


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, encoding="utf-8", errors="surrogateescape")
    if check and result.returncode != 0:
        joined = " ".join(cmd)
        raise CommandError(joined, result.returncode, result.stdout, result.stderr)
    return result


def repo_root(path: Path) -> Path:
    result = run(["git", "-C", str(path), "rev-parse", "--show-toplevel"])
    return Path(result.stdout.strip()).resolve()


def current_branch(repo: Path) -> str:
    return run(["git", "-C", str(repo), "branch", "--show-current"]).stdout.strip()


def status_short(repo: Path) -> str:
    return run(["git", "-C", str(repo), "status", "--short"]).stdout


def read_commits(values: list[str], commit_file: str | None) -> list[str]:
    commits = list(values)
    if commit_file:
        for line in Path(commit_file).expanduser().read_text(encoding="utf-8-sig").splitlines():
            clean = line.strip()
            if clean and not clean.startswith("#"):
                commits.append(clean)
    return commits


def configure_source_remote(repo: Path, remote: str, source_repo: str) -> None:
    existing = run(["git", "-C", str(repo), "remote", "get-url", remote], check=False)
    if existing.returncode == 0:
        if existing.stdout.strip() != source_repo:
            run(["git", "-C", str(repo), "remote", "set-url", remote, source_repo])
    else:
        run(["git", "-C", str(repo), "remote", "add", remote, source_repo])
    run(["git", "-C", str(repo), "fetch", "--tags", "--prune", remote])


def verify_commits(repo: Path, commits: list[str]) -> None:
    missing: list[str] = []
    for commit in commits:
        result = run(["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"], check=False)
        if result.returncode != 0:
            missing.append(commit)
    if missing:
        raise SystemExit(f"Unknown commit/ref in target repository after fetch: {', '.join(missing)}")


def write_summary(path: str | None, text: str) -> None:
    if not path:
        return
    out = Path(path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply selected ReleaseGo commits or patches without auto-commit.")
    parser.add_argument("--target-repo", required=True, help="Local target git repository path.")
    parser.add_argument("--target-branch", required=True, help="Expected current branch. The script will not switch branches.")
    parser.add_argument("--source-repo", help="Source git repository URL for cherry-pick mode.")
    parser.add_argument("--source-remote", default="releasego-source", help="Temporary remote name for source repo.")
    parser.add_argument("--commits", nargs="*", default=[], help="Commit SHAs or refs to cherry-pick with -n.")
    parser.add_argument("--commit-file", help="File containing one commit/ref per line.")
    parser.add_argument("--patch", help="Patch file to apply with git apply --3way.")
    parser.add_argument("--strategy", choices=["auto", "cherry-pick", "patch"], default="auto")
    parser.add_argument("--mainline", type=int, help="Mainline parent for cherry-picking merge commits.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow applying on top of a dirty worktree.")
    parser.add_argument("--summary-out", help="Optional path for a Markdown migration summary.")
    args = parser.parse_args()

    try:
        target = repo_root(Path(args.target_repo).expanduser().resolve())
    except CommandError as exc:
        raise SystemExit(f"Target path is not a git repository: {args.target_repo}\n{exc.stderr.strip()}")

    branch = current_branch(target)
    if branch != args.target_branch:
        raise SystemExit(f"Branch mismatch: expected {args.target_branch}, current {branch}. Checkout the target branch yourself first.")

    dirty_before = status_short(target)
    if dirty_before and not args.allow_dirty:
        raise SystemExit("Dirty worktree refused. Commit/stash/clean existing changes or pass --allow-dirty explicitly.")

    commits = read_commits(args.commits, args.commit_file)
    strategy = args.strategy
    if strategy == "auto":
        strategy = "cherry-pick" if commits else "patch"

    if strategy == "cherry-pick":
        if not commits:
            raise SystemExit("No commits provided for cherry-pick mode.")
        if not args.source_repo:
            raise SystemExit("--source-repo is required for cherry-pick mode.")
        configure_source_remote(target, args.source_remote, args.source_repo)
        verify_commits(target, commits)
        cmd = ["git", "-C", str(target), "cherry-pick", "-n"]
        if args.mainline:
            cmd.extend(["-m", str(args.mainline)])
        cmd.extend(commits)
        applied_by = "cherry-pick -n"
    else:
        if not args.patch:
            raise SystemExit("No --patch provided for patch mode.")
        patch_path = Path(args.patch).expanduser().resolve()
        if not patch_path.exists():
            raise SystemExit(f"Patch file not found: {patch_path}")
        cmd = ["git", "-C", str(target), "apply", "--3way", str(patch_path)]
        applied_by = "git apply --3way"

    try:
        run(cmd)
    except CommandError as exc:
        recovery = "Resolve conflicts, then continue manually; use `git cherry-pick --abort` for failed cherry-pick state or `git apply --abort` when applicable."
        print("Status: failed")
        print("Stop point: conflict or apply failure")
        print(f"Command: {exc.command}")
        print(f"Exit code: {exc.code}")
        if exc.stdout.strip():
            print(exc.stdout.strip())
        if exc.stderr.strip():
            print(exc.stderr.strip())
        print(f"Recovery: {recovery}")
        return exc.code

    after = status_short(target)
    summary = "\n".join([
        f"# ReleaseGo Migration: {target}",
        "",
        "Status: success",
        f"Target repo: {target}",
        f"Target branch: {branch}",
        f"Source repo: {args.source_repo or args.patch}",
        f"Applied by: {applied_by}",
        f"Commits/patch: {', '.join(commits) if commits else args.patch}",
        "Auto commit: no",
        "",
        "## Working Tree",
        "```text",
        after.rstrip() or "(clean)",
        "```",
        "",
    ])
    write_summary(args.summary_out, summary)
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
