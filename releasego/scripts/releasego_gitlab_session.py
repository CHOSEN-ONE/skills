#!/usr/bin/env python3
"""Browserless GitLab session helpers for git.tingyun.com."""

from __future__ import annotations

import argparse
import http.cookiejar
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from releasego_config import ReleaseGoConfig, load_config
from releasego_security import Redactor, SameOriginRedirectHandler, validated_origin, require_same_origin, safe_json


DEFAULT_TIMEOUT = 25


@dataclass
class HttpResponse:
    status: int
    url: str
    content_type: str
    data: Any | None
    text: str


class GitLabHttpSession:
    def __init__(self, config: ReleaseGoConfig, timeout: int = DEFAULT_TIMEOUT):
        self.config = config
        self.base_url = config.gitlab_base_url.rstrip("/")
        self.timeout = timeout
        self.allow_http = config.gitlab_allow_http
        validated_origin(self.base_url, allow_http=self.allow_http)
        self.redactor = Redactor((config.username, config.password))
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar), SameOriginRedirectHandler(self.base_url, allow_http=self.allow_http))

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = self.base_url + "/" + path.lstrip("/")
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        form_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        data = None
        request_headers = {
            "User-Agent": "Mozilla/5.0 ReleaseGoShare/1.0",
            "Accept": "application/json, text/html, */*",
        }
        if headers:
            request_headers.update(headers)
        if form_body is not None:
            data = urllib.parse.urlencode(form_body).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(require_same_origin(self._url(path, params), self.base_url, allow_http=self.allow_http), data=data, headers=request_headers, method=method.upper())
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
                status = resp.status
                final_url = resp.geturl()
                content_type = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
            final_url = exc.geturl()
            content_type = exc.headers.get("Content-Type", "")
        except (urllib.error.URLError, OSError) as exc:
            raise SystemExit("GitLab request failed; check the configured endpoint, network and TLS trust for HTTPS. No automatic scheme fallback.") from None

        text = raw.decode("utf-8", errors="replace")
        parsed = None
        if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        return HttpResponse(status=status, url=final_url, content_type=content_type, data=parsed, text=text)

    @staticmethod
    def _csrf_from_html(text: str) -> str:
        match = re.search(r'name=["\']authenticity_token["\']\s+value=["\']([^"\']+)["\']', text)
        if not match:
            raise SystemExit("GitLab sign-in page did not contain authenticity_token")
        return html.unescape(match.group(1))

    def login(self) -> HttpResponse:
        if not self.config.username or not self.config.password:
            raise SystemExit("Missing Tingyun credentials. Configure config.local.json or environment variables.")

        last_status: int | None = None
        last_response: HttpResponse | None = None
        for attempt in range(1, 4):
            sign_in = self._request("GET", "/users/sign_in", headers={"Accept": "text/html,application/xhtml+xml,*/*"})
            token = self._csrf_from_html(sign_in.text)
            response = self._request(
                "POST",
                "/users/auth/ldapmain/callback",
                form_body={
                    "authenticity_token": token,
                    "username": self.config.username,
                    "password": self.config.password,
                    "remember_me": "0",
                },
                headers={"Referer": sign_in.url, "Accept": "text/html,application/xhtml+xml,*/*"},
            )
            user = self.current_user(retry_login=False)
            if user.status == 200 and isinstance(user.data, dict):
                return response
            last_status = user.status
            last_response = response
            if attempt < 3:
                time.sleep(1)
        raise SystemExit(f"GitLab LDAP login failed: API user check returned HTTP {last_status}; last login URL {self.redactor.text(last_response.url) if last_response else 'unknown'}")

    def current_user(self, retry_login: bool = True) -> HttpResponse:
        response = self._request("GET", "/api/v4/user")
        if retry_login and response.status in {401, 403}:
            self.login()
            response = self._request("GET", "/api/v4/user")
        return response

    def api_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        retry_login: bool = True,
        method: str = "GET",
        form_body: dict[str, Any] | None = None,
    ) -> HttpResponse:
        response = self._request(method, path, params=params, form_body=form_body)
        if retry_login and response.status in {401, 403}:
            self.login()
            response = self._request(method, path, params=params, form_body=form_body)
        if response.data is None:
            raise SystemExit(f"Expected GitLab JSON but received HTTP {response.status} {response.content_type}: {self.redactor.text(response.text)[:200]!r}")
        return response

    def project_search(self, query: str, per_page: int = 5) -> HttpResponse:
        return self.api_json("/api/v4/projects", {"search": query, "simple": "true", "per_page": per_page})

    def project(self, path_with_namespace: str) -> HttpResponse:
        encoded = urllib.parse.quote(path_with_namespace, safe="")
        return self.api_json(f"/api/v4/projects/{encoded}")

    def compare(self, path_with_namespace: str, base: str, head: str) -> HttpResponse:
        encoded = urllib.parse.quote(path_with_namespace, safe="")
        return self.api_json(f"/api/v4/projects/{encoded}/repository/compare", {"from": base, "to": head})

    def branches(self, path_with_namespace: str, search: str | None = None, per_page: int = 20) -> HttpResponse:
        encoded = urllib.parse.quote(path_with_namespace, safe="")
        return self.api_json(f"/api/v4/projects/{encoded}/repository/branches", {"search": search, "per_page": per_page})

    def tags(self, path_with_namespace: str, search: str | None = None, per_page: int = 20) -> HttpResponse:
        encoded = urllib.parse.quote(path_with_namespace, safe="")
        return self.api_json(f"/api/v4/projects/{encoded}/repository/tags", {"search": search, "per_page": per_page})

    def commits(self, path_with_namespace: str, ref_name: str, per_page: int = 20) -> HttpResponse:
        encoded = urllib.parse.quote(path_with_namespace, safe="")
        return self.api_json(f"/api/v4/projects/{encoded}/repository/commits", {"ref_name": ref_name, "per_page": per_page})

    def commit_diff(self, path_with_namespace: str, sha: str, per_page: int = 100) -> HttpResponse:
        encoded = urllib.parse.quote(path_with_namespace, safe="")
        return self.api_json(f"/api/v4/projects/{encoded}/repository/commits/{sha}/diff", {"per_page": per_page})

    def create_tag(self, path_with_namespace: str, tag_name: str, ref: str, message: str | None = None) -> HttpResponse:
        encoded = urllib.parse.quote(path_with_namespace, safe="")
        body = {"tag_name": tag_name, "ref": ref}
        if message:
            body["message"] = message
        return self.api_json(f"/api/v4/projects/{encoded}/repository/tags", method="POST", form_body=body)




def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Use GitLab APIs without browser automation.")
    parser.add_argument("--skill-root", type=Path)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login-test", help="Login through the GitLab LDAP callback and call /api/v4/user.")
    search = sub.add_parser("project-search", help="Search GitLab projects.")
    search.add_argument("--query", required=True)
    search.add_argument("--per-page", type=int, default=5)

    project = sub.add_parser("project-info", help="Read one project by path_with_namespace.")
    project.add_argument("--project", required=True)

    compare = sub.add_parser("compare", help="Run GitLab repository compare.")
    compare.add_argument("--project", required=True)
    compare.add_argument("--from-ref", required=True)
    compare.add_argument("--to-ref", required=True)
    compare.add_argument("--full", action="store_true", help="Print full compare JSON. Default prints a compact summary.")

    branches = sub.add_parser("branches", help="List project branches.")
    branches.add_argument("--project", required=True)
    branches.add_argument("--search")
    branches.add_argument("--per-page", type=int, default=20)

    tags = sub.add_parser("tags", help="List project tags.")
    tags.add_argument("--project", required=True)
    tags.add_argument("--search")
    tags.add_argument("--per-page", type=int, default=20)

    commits = sub.add_parser("commits", help="List commits for a ref.")
    commits.add_argument("--project", required=True)
    commits.add_argument("--ref", required=True)
    commits.add_argument("--per-page", type=int, default=20)

    commit_diff = sub.add_parser("commit-diff", help="List file diffs for a commit.")
    commit_diff.add_argument("--project", required=True)
    commit_diff.add_argument("--sha", required=True)
    commit_diff.add_argument("--per-page", type=int, default=100)

    create_tag = sub.add_parser("create-tag", help="Try creating a GitLab tag through the GitLab API. This may be unavailable on this instance and has side effects.")
    create_tag.add_argument("--project", required=True)
    create_tag.add_argument("--tag-name", required=True)
    create_tag.add_argument("--ref", required=True)
    create_tag.add_argument("--message")
    create_tag.add_argument("--confirm-write", choices=["yes"], required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cfg = load_config(args.skill_root, require_credentials=True)
    session = GitLabHttpSession(cfg, timeout=args.timeout)
    safe_json = session.redactor.json

    if args.command == "login-test":
        session.login()
        user = session.current_user(retry_login=False)
        print(
            safe_json(
                {
                    "httpStatus": user.status,
                    "credentialSource": cfg.credential_source,
                    "hasUsername": bool(cfg.username),
                    "hasPassword": bool(cfg.password),
                    "userApiKeys": sorted(user.data.keys()) if isinstance(user.data, dict) else None,
                    "usernamePresent": bool(user.data.get("username")) if isinstance(user.data, dict) else None,
                }
            )
        )
        return 0

    session.login()

    if args.command == "project-search":
        response = session.project_search(args.query, args.per_page)
        projects = response.data if isinstance(response.data, list) else []
        print(
            safe_json(
                {
                    "httpStatus": response.status,
                    "count": len(projects),
                    "projects": [
                        {
                            "id": item.get("id"),
                            "path_with_namespace": item.get("path_with_namespace"),
                            "ssh_url_to_repo": item.get("ssh_url_to_repo"),
                        }
                        for item in projects
                    ],
                }
            )
        )
        return 0

    if args.command == "project-info":
        response = session.project(args.project)
        data = response.data if isinstance(response.data, dict) else {}
        print(
            safe_json(
                {
                    "httpStatus": response.status,
                    "id": data.get("id"),
                    "path_with_namespace": data.get("path_with_namespace"),
                    "default_branch": data.get("default_branch"),
                    "ssh_url_to_repo": data.get("ssh_url_to_repo"),
                    "web_url": data.get("web_url"),
                }
            )
        )
        return 0

    if args.command == "compare":
        response = session.compare(args.project, args.from_ref, args.to_ref)
        if args.full:
            print(safe_json(response.data))
        else:
            data = response.data if isinstance(response.data, dict) else {}
            print(
                safe_json(
                    {
                        "httpStatus": response.status,
                        "web_url": data.get("web_url"),
                        "commitCount": len(data.get("commits", [])) if isinstance(data.get("commits"), list) else None,
                        "diffCount": len(data.get("diffs", [])) if isinstance(data.get("diffs"), list) else None,
                        "compare_timeout": data.get("compare_timeout"),
                        "compare_same_ref": data.get("compare_same_ref"),
                    }
                )
        )
        return 0

    if args.command == "branches":
        response = session.branches(args.project, args.search, args.per_page)
        rows = response.data if isinstance(response.data, list) else []
        print(safe_json({"httpStatus": response.status, "count": len(rows), "branches": [{"name": item.get("name"), "merged": item.get("merged"), "protected": item.get("protected"), "web_url": item.get("web_url")} for item in rows]}))
        return 0

    if args.command == "tags":
        response = session.tags(args.project, args.search, args.per_page)
        rows = response.data if isinstance(response.data, list) else []
        print(safe_json({"httpStatus": response.status, "count": len(rows), "tags": [{"name": item.get("name"), "target": item.get("target"), "protected": item.get("protected")} for item in rows]}))
        return 0

    if args.command == "commits":
        response = session.commits(args.project, args.ref, args.per_page)
        rows = response.data if isinstance(response.data, list) else []
        print(safe_json({"httpStatus": response.status, "count": len(rows), "commits": [{"id": item.get("id"), "short_id": item.get("short_id"), "title": item.get("title"), "committed_date": item.get("committed_date"), "web_url": item.get("web_url")} for item in rows]}))
        return 0

    if args.command == "commit-diff":
        response = session.commit_diff(args.project, args.sha, args.per_page)
        rows = response.data if isinstance(response.data, list) else []
        print(safe_json({"httpStatus": response.status, "count": len(rows), "diffs": [{"old_path": item.get("old_path"), "new_path": item.get("new_path"), "new_file": item.get("new_file"), "deleted_file": item.get("deleted_file"), "renamed_file": item.get("renamed_file")} for item in rows]}))
        return 0

    if args.command == "create-tag":
        if args.confirm_write != "yes":
            raise SystemExit("This command creates a GitLab tag. Re-run with --confirm-write yes after verifying all arguments.")
        response = session.create_tag(args.project, args.tag_name, args.ref, args.message)
        data = response.data if isinstance(response.data, dict) else {}
        print(safe_json({"httpStatus": response.status, "name": data.get("name"), "target": data.get("target"), "message": data.get("message")}))
        return 0 if 200 <= response.status < 300 and data.get("name") else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
