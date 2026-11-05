#!/usr/bin/env python3
"""Load local ReleaseGo skill configuration without exposing secrets."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from releasego_security import Redactor


DEFAULT_RELEASEGO_BASE_URL = "https://releasego.tingyun.com"
DEFAULT_GITLAB_BASE_URL = "https://git.tingyun.com"
DEFAULT_JENKINS_BASE_URL = "https://jenkins-new.tingyun.com"
DEFAULT_BROWSER_CDP = "http://127.0.0.1:9222"


@dataclass(frozen=True)
class ReleaseGoConfig:
    skill_root: Path
    config_path: Path
    username: str | None = field(repr=False)
    password: str | None = field(repr=False)
    releasego_base_url: str
    gitlab_base_url: str
    jenkins_base_url: str
    browser_cdp: str
    chrome_path: str | None
    work_dir: str | None
    credential_source: str
    gitlab_allow_http: bool = False

    @property
    def has_credentials(self) -> bool:
        return bool(self.username and self.password)

    def safe_dict(self) -> dict[str, Any]:
        return Redactor((self.username, self.password)).scrub({
            "skillRoot": str(self.skill_root),
            "configPath": str(self.config_path),
            "hasUsername": bool(self.username),
            "hasPassword": bool(self.password),
            "credentialSource": self.credential_source,
            "releasegoBaseUrl": self.releasego_base_url,
            "gitlabBaseUrl": self.gitlab_base_url,
            "gitlabAllowHttp": self.gitlab_allow_http,
            "jenkinsBaseUrl": self.jenkins_base_url,
            "browserCdp": self.browser_cdp,
            "hasChromePath": bool(self.chrome_path),
            "workDir": self.work_dir,
        })


def skill_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def read_local_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in local config: {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Local config must be a JSON object: {config_path}")
    return data


def first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def expanded_path(value: str | None) -> str | None:
    return str(Path(os.path.expandvars(value)).expanduser().resolve()) if value else None


def gitlab_http_opt_in(local: dict[str, Any]) -> bool:
    if "gitlabAllowHttp" in local:
        if not isinstance(local["gitlabAllowHttp"], bool):
            raise SystemExit("gitlabAllowHttp must be a JSON boolean.")
        return local["gitlabAllowHttp"]
    raw = os.environ.get("RELEASEGO_GITLAB_ALLOW_HTTP", "false").strip().lower()
    if raw not in {"true", "false", "1", "0"}:
        raise SystemExit("RELEASEGO_GITLAB_ALLOW_HTTP must be true, false, 1 or 0.")
    return raw in {"true", "1"}


def work_directory(config: ReleaseGoConfig) -> Path:
    return Path(config.work_dir) if config.work_dir else Path.cwd() / ".releasego"


def load_config(skill_root: Path | None = None, require_credentials: bool = False) -> ReleaseGoConfig:
    root = (skill_root or skill_root_from_script()).resolve()
    config_path = root / "config.local.json"
    local = read_local_config(config_path)

    username = first_string(local.get("username"), os.environ.get("TINGYUN_USERNAME"))
    password = first_string(local.get("password"), os.environ.get("TINGYUN_PASSWORD"))
    credential_source = "none"
    if local.get("username") or local.get("password"):
        credential_source = "config.local.json"
    elif os.environ.get("TINGYUN_USERNAME") or os.environ.get("TINGYUN_PASSWORD"):
        credential_source = "environment"

    cfg = ReleaseGoConfig(
        skill_root=root,
        config_path=config_path,
        username=username,
        password=password,
        releasego_base_url=first_string(local.get("releasegoBaseUrl"), os.environ.get("RELEASEGO_BASE_URL")) or DEFAULT_RELEASEGO_BASE_URL,
        gitlab_base_url=first_string(local.get("gitlabBaseUrl"), os.environ.get("RELEASEGO_GITLAB_BASE_URL")) or DEFAULT_GITLAB_BASE_URL,
        jenkins_base_url=first_string(local.get("jenkinsBaseUrl"), os.environ.get("RELEASEGO_JENKINS_BASE_URL")) or DEFAULT_JENKINS_BASE_URL,
        browser_cdp=first_string(local.get("browserCdp"), os.environ.get("RELEASEGO_BROWSER_CDP")) or DEFAULT_BROWSER_CDP,
        chrome_path=expanded_path(first_string(local.get("chromePath"), os.environ.get("RELEASEGO_CHROME_PATH"))),
        work_dir=expanded_path(first_string(local.get("workDir"), os.environ.get("RELEASEGO_WORK_DIR"))),
        credential_source=credential_source,
        gitlab_allow_http=gitlab_http_opt_in(local),
    )

    if require_credentials and not cfg.has_credentials:
        raise SystemExit(
            "Missing Tingyun credentials. Create <skill-root>/config.local.json from config.example.json "
            "or set TINGYUN_USERNAME and TINGYUN_PASSWORD."
        )
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(description="Load ReleaseGo skill local configuration.")
    parser.add_argument("--skill-root", type=Path, help="Skill root directory. Defaults to this script's parent skill directory.")
    parser.add_argument("--require-credentials", action="store_true", help="Exit non-zero if credentials are not configured.")
    parser.add_argument("--json", action="store_true", help="Print a JSON summary without secrets.")
    args = parser.parse_args()

    cfg = load_config(args.skill_root, require_credentials=args.require_credentials)
    if args.json:
        print(json.dumps(cfg.safe_dict(), ensure_ascii=False, indent=2))
    else:
        safe = cfg.safe_dict()
        for key, value in safe.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
