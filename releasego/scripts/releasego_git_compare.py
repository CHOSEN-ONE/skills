#!/usr/bin/env python3
"""Generate GitLab-style compare artifacts for a ReleaseGo app/config."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

from releasego_config import load_config, work_directory


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, encoding="utf-8", errors="surrogateescape")
    if check and result.returncode != 0:
        joined = " ".join(cmd)
        raise SystemExit(f"Command failed ({result.returncode}): {joined}\n{result.stderr.strip()}")
    return result


def slug_for_repo(repo_url: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9_.-]+", "_", repo_url).strip("_")
    digest = hashlib.sha1(repo_url.encode("utf-8")).hexdigest()[:10]
    return f"{readable[:80]}_{digest}.git"


def ensure_mirror(repo_url: str, cache_root: Path) -> Path:
    cache_root.mkdir(parents=True, exist_ok=True)
    repo_dir = cache_root / slug_for_repo(repo_url)
    if repo_dir.exists():
        run(["git", "-C", str(repo_dir), "remote", "set-url", "origin", repo_url])
        run(["git", "-C", str(repo_dir), "remote", "update", "--prune", "origin"])
    else:
        run(["git", "clone", "--mirror", repo_url, str(repo_dir)])
    return repo_dir


def resolve_ref(repo_dir: Path, ref: str) -> str:
    candidates = [ref, f"refs/tags/{ref}", f"refs/heads/{ref}"]
    for candidate in candidates:
        result = run(["git", "-C", str(repo_dir), "rev-parse", "--verify", f"{candidate}^{{commit}}"], check=False)
        if result.returncode == 0:
            return result.stdout.strip()
    raise SystemExit(f"Git ref not found in {repo_dir}: {ref}")


def gitlab_compare_url(repo_url: str, base: str, head: str, base_url: str) -> str | None:
    repo_path: str | None = None
    scp_match = re.match(r"git@[^:]+:(?P<path>.+?)(?:\.git)?$", repo_url)
    if scp_match:
        repo_path = scp_match.group("path")
    else:
        http_match = re.match(r"https?://[^/]+/(?P<path>.+?)(?:\.git)?$", repo_url)
        if http_match:
            repo_path = http_match.group("path")
    if not repo_path:
        return None
    quoted_path = "/".join(quote(part, safe="") for part in repo_path.split("/"))
    return f"{base_url.rstrip('/')}/{quoted_path}/-/compare/{quote(base, safe='')}...{quote(head, safe='')}"


def parse_commits(raw: str) -> list[dict[str, str]]:
    commits: list[dict[str, str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 3)
        while len(parts) < 4:
            parts.append("")
        commits.append({"sha": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3]})
    return commits


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", errors="surrogateescape", newline="\n")


def path_args(paths: list[str]) -> list[str]:
    return ["--", *paths] if paths else []


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate git compare artifacts for a ReleaseGo item.")
    parser.add_argument("--repo-url", required=True, help="Git repository URL.")
    parser.add_argument("--base", required=True, help="Base ref from the base release.")
    parser.add_argument("--head", required=True, help="Head ref from the requested release.")
    parser.add_argument("--out", required=True, help="Output directory for report artifacts.")
    parser.add_argument("--repo-cache", help="Mirror cache directory; defaults to configured work directory / git-cache.")
    parser.add_argument("--paths", nargs="*", default=[], help="Optional path filters inside the repository.")
    parser.add_argument("--label", default="", help="Display label for the compared item.")
    parser.add_argument("--gitlab-base-url", help="Override the configured GitLab base URL for compare links.")
    args = parser.parse_args()

    cfg = load_config()
    out_dir = Path(args.out).expanduser().resolve()
    cache_root = Path(args.repo_cache).expanduser().resolve() if args.repo_cache else work_directory(cfg) / "git-cache"
    repo_dir = ensure_mirror(args.repo_url, cache_root)

    base_sha = resolve_ref(repo_dir, args.base)
    head_sha = resolve_ref(repo_dir, args.head)
    extra_paths = path_args(args.paths)

    log_format = "%H%x09%an%x09%ad%x09%s"
    commits_raw = run([
        "git", "-C", str(repo_dir), "log", "--reverse", "--date=iso-strict",
        f"--pretty=format:{log_format}", f"{base_sha}..{head_sha}", *extra_paths
    ]).stdout
    name_status = run(["git", "-C", str(repo_dir), "diff", "--name-status", "--find-renames", base_sha, head_sha, *extra_paths]).stdout
    stat = run(["git", "-C", str(repo_dir), "diff", "--stat", base_sha, head_sha, *extra_paths]).stdout
    # Patch bytes must retain CRLF and non-UTF-8 source content exactly.
    patch = subprocess.run(["git", "-C", str(repo_dir), "diff", "--binary", base_sha, head_sha, *extra_paths], capture_output=True, check=True).stdout

    commits = parse_commits(commits_raw)
    files = [line for line in name_status.splitlines() if line.strip()]
    compare_url = gitlab_compare_url(args.repo_url, args.base, args.head, args.gitlab_base_url or cfg.gitlab_base_url)

    write_text(out_dir / "commits.tsv", commits_raw + ("\n" if commits_raw else ""))
    write_text(out_dir / "files.txt", name_status)
    write_text(out_dir / "stat.txt", stat)
    (out_dir / "diff.patch").write_bytes(patch)

    summary_lines = [
        f"# ReleaseGo Compare: {args.label or args.repo_url}",
        "",
        "Status: success",
        f"Repository: {args.repo_url}",
        f"Base ref: {args.base}",
        f"Base sha: {base_sha}",
        f"Head ref: {args.head}",
        f"Head sha: {head_sha}",
        f"GitLab compare: {compare_url or 'unavailable'}",
        f"Output directory: {out_dir}",
        "",
        "## Summary",
        f"- Commits: {len(commits)}",
        f"- Changed files: {len(files)}",
        f"- Patch: {out_dir / 'diff.patch'}",
        "",
        "## Commits",
    ]
    if commits:
        summary_lines.extend(f"- `{c['sha'][:12]}` {c['date']} {c['author']} - {c['subject']}" for c in commits)
    else:
        summary_lines.append("- No commits in range.")
    summary_lines.extend(["", "## Files"])
    summary_lines.extend(files or ["- No file changes."])
    write_text(out_dir / "summary.md", "\n".join(summary_lines) + "\n")

    payload = {
        "repo_url": args.repo_url,
        "base_ref": args.base,
        "base_sha": base_sha,
        "head_ref": args.head,
        "head_sha": head_sha,
        "gitlab_compare": compare_url,
        "paths": args.paths,
        "commit_count": len(commits),
        "changed_file_count": len(files),
        "commits": commits,
        "files": files,
    }
    write_text(out_dir / "compare.json", json.dumps(payload, ensure_ascii=False, indent=2))
    print(out_dir / "summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
