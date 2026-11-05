#!/usr/bin/env python3
"""Read-only environment diagnostics for releasego."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from releasego_config import load_config
from releasego_security import Redactor


def run_version(command: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=10, encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - diagnostics should not crash on missing tools
        return {"available": False, "error": str(exc)}
    return {
        "available": result.returncode == 0,
        "returnCode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def check_cdp(url: str) -> dict[str, Any]:
    version_url = url.rstrip("/") + "/json/version"
    try:
        with urllib.request.urlopen(version_url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {"available": True, "url": version_url, "browser": payload.get("Browser"), "webSocketDebuggerUrl": bool(payload.get("webSocketDebuggerUrl"))}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"available": False, "url": version_url, "error": str(exc)}


def chrome_candidates(configured: str | None) -> list[str]:
    candidates: list[str] = []
    if configured:
        candidates.append(str(Path(configured).expanduser()))
    if platform.system() == "Windows":
        candidates.extend([
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ])
        candidates.append(str(Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Google" / "Chrome" / "Application" / "chrome.exe"))
    elif platform.system() == "Darwin":
        candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        candidates.append(str(Path.home() / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"))
    for name in ("google-chrome", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose releasego local environment without modifying it.")
    parser.add_argument("--skill-root", type=Path, help="Skill root directory. Defaults to this script's parent skill directory.")
    parser.add_argument("--json", action="store_true", help="Print JSON diagnostics.")
    args = parser.parse_args()

    cfg = load_config(args.skill_root, require_credentials=False)
    candidates = chrome_candidates(cfg.chrome_path)
    report = {
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "python": {"executable": sys.executable, "version": sys.version.split()[0]},
        "git": {"path": shutil.which("git"), "version": run_version(["git", "--version"])},
        "agentBrowser": {"agent-browser": shutil.which("agent-browser"), "agent-browser.cmd": shutil.which("agent-browser.cmd")},
        "config": cfg.safe_dict(),
        "cdp": check_cdp(cfg.browser_cdp),
        "chromeCandidates": [{"path": item, "exists": Path(item).exists()} for item in candidates],
        "packagingRisk": {"configLocalInSkillRoot": (cfg.skill_root / "config.local.json").exists()},
    }
    report = Redactor((cfg.username, cfg.password)).scrub(report)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Platform: {report['platform']['system']} {report['platform']['release']} {report['platform']['machine']}")
        print(f"Python: {report['python']['executable']} ({report['python']['version']})")
        print(f"Git: {report['git']['path'] or 'not found'}")
        print(f"CDP: {'available' if report['cdp']['available'] else 'unavailable'} {report['cdp'].get('url')}")
        print(f"Credentials: username={report['config']['hasUsername']} password={report['config']['hasPassword']} source={report['config']['credentialSource']}")
        print(f"config.local.json packaging risk: {report['packagingRisk']['configLocalInSkillRoot']}")
        found_chrome = [item for item in report['chromeCandidates'] if item['exists']]
        print(f"Chrome candidates found: {len(found_chrome)}")
    return 1 if report["packagingRisk"]["configLocalInSkillRoot"] else 0


if __name__ == "__main__":
    sys.exit(main())
