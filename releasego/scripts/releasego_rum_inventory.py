#!/usr/bin/env python3
"""Print known RUM app/config/dependency repositories for Wukong or Guanyun."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


SHARED_DEPENDENCIES = [
    {
        "name": "app-dc-common",
        "repo": "http://git.tingyun.com/app3/app-dc-common",
        "notes": "Shared by Wukong and Guanyun. Fetch source only when the requested change requires modifying this package.",
    },
]


INVENTORY: dict[str, dict[str, Any]] = {
    "3.0": {
        "display": "3.0 / 悟空",
        "aliases": ["3.0", "wukong", "悟空"],
        "dependencies": SHARED_DEPENDENCIES,
        "configs": [
            {"name": "schema-repo-app", "repo": "git@git.tingyun.com:3.0-operation/schema-repo-app.git"},
            {"name": "schema-repo-common", "repo": "git@git.tingyun.com:3.0-operation/schema-repo-common.git"},
            {"name": "schema-repo-browser", "repo": "git@git.tingyun.com:3.0-operation/schema-repo-browser.git"},
            {"name": "schema-repo-mp", "repo": "git@git.tingyun.com:3.0-operation/schema-repo-mp.git"},
        ],
        "apps": [
            {
                "name": "common-js-config",
                "repo": "git@git.tingyun.com:mp/mp-config-server.git",
                "jenkins": "https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/common/job/common-js-config/",
            },
            {
                "name": "app-dc-frontend",
                "repo": "git@git.tingyun.com:app3/app-dc-frontend.git",
                "jenkins": "https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/app/job/app-dc-frontend/",
            },
            {
                "name": "mp-api",
                "repo": "git@git.tingyun.com:mp/mp-report.git",
                "jenkins": "https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/mp/job/mp-api/",
            },
            {
                "name": "browser-api",
                "repo": "git@git.tingyun.com:eui-browser/browser-api.git",
                "jenkins": "https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/browser/job/browser-api/",
            },
            {
                "name": "app-deobfuscator-dubbo",
                "repo": "git@git.tingyun.com:app3/app-deobfuscator.git",
                "jenkins": "https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/app/job/app-deobfuscator-dubbo/",
                "notes": "Same repository family as 4.0 rum-dbg; branch distinguishes version line.",
            },
            {
                "name": "app-api",
                "repo": "git@git.tingyun.com:app3/app-api.git",
                "jenkins": "https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/app/job/app-api/",
            },
            {
                "name": "common-rum-wrap",
                "repo": "git@git.tingyun.com:app3/rum-wrap.git",
                "jenkins": "https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/common/job/common-rum-wrap/",
            },
        ],
    },
    "4.0": {
        "display": "4.0 / 观云",
        "aliases": ["4.0", "guanyun", "观云"],
        "dependencies": SHARED_DEPENDENCIES,
        "configs": [
            {"name": "schema-repo-guanyun", "repo": "git@git.tingyun.com:4.0-operation/schema-repo-guanyun.git"},
            {"name": "schema-repo-common", "repo": "git@git.tingyun.com:4.0-operation/schema-repo-common.git"},
            {"name": "schema-repo-rum", "repo": "git@git.tingyun.com:4.0-operation/schema-repo-rum.git"},
        ],
        "apps": [
            {
                "name": "rum-wrap",
                "repo": "git@git.tingyun.com:o11y-rum/rum-wrap.git",
                "notes": "Split from 3.0 app.",
            },
            {
                "name": "rum-dc",
                "repo": "git@git.tingyun.com:o11y-rum/rum-dc.git",
                "notes": "Split from 3.0 app.",
            },
            {
                "name": "rum-dbg",
                "repo": "git@git.tingyun.com:app3/app-deobfuscator.git",
                "notes": "Same repository as 3.0 app-deobfuscator-dubbo; branch distinguishes version line.",
            },
            {
                "name": "guanyun-api / tingyun-observable-rum",
                "repo": "git@git.tingyun.com:guanyun-api-group/observable-api.git",
                "notes": "tingyun-observable-rum submodule/module inside guanyun-api context.",
            },
        ],
    },
}


def normalize_line(value: str) -> str:
    needle = value.strip().lower()
    for key, data in INVENTORY.items():
        aliases = [str(alias).lower() for alias in data["aliases"]]
        if needle == key or needle in aliases:
            return key
    raise SystemExit(f"Unknown line: {value}. Use one of: 3.0, 悟空, 4.0, 观云.")


def select_items(data: dict[str, Any], kind: str) -> dict[str, list[dict[str, str]]]:
    if kind == "all":
        return {"configs": data["configs"], "apps": data["apps"], "dependencies": data["dependencies"]}
    return {kind: data[kind]}


def as_markdown(line_key: str, kind: str) -> str:
    data = INVENTORY[line_key]
    selected = select_items(data, kind)
    lines = [f"# RUM Inventory: {data['display']}", ""]
    for section_key, title in (("configs", "Configs"), ("apps", "Apps"), ("dependencies", "Dependencies")):
        if section_key not in selected:
            continue
        lines.extend([f"## {title}", "", "| Name | Repository | Jenkins | Notes |", "| --- | --- | --- | --- |"])
        for item in selected[section_key]:
            jenkins = item.get("jenkins", "")
            jenkins_cell = f"`{jenkins}`" if jenkins else ""
            lines.append(f"| {item['name']} | `{item['repo']}` | {jenkins_cell} | {item.get('notes', '')} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def as_json(line_key: str, kind: str) -> str:
    data = INVENTORY[line_key]
    payload = {
        "line": line_key,
        "display": data["display"],
        "aliases": data["aliases"],
        **select_items(data, kind),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="List known ReleaseGo RUM app/config/dependency repositories by version line.")
    parser.add_argument("--line", required=True, help="Version line: 3.0, 悟空, 4.0, or 观云.")
    parser.add_argument("--kind", choices=["all", "apps", "configs", "dependencies"], default="all", help="Inventory kind to print. Dependencies are shared internal packages.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format.")
    args = parser.parse_args()

    line_key = normalize_line(args.line)
    if args.format == "json":
        sys.stdout.write(as_json(line_key, args.kind))
    else:
        sys.stdout.write(as_markdown(line_key, args.kind))
    return 0


if __name__ == "__main__":
    sys.exit(main())
