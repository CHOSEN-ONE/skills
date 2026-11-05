#!/usr/bin/env python3
"""Browserless ReleaseGo HTTP session helpers.

This script intentionally keeps cookies in memory by default and never prints
credential values.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from releasego_config import ReleaseGoConfig, load_config
from releasego_security import Redactor, SameOriginRedirectHandler, https_origin, require_same_origin, safe_json


DEFAULT_TIMEOUT = 20


@dataclass
class JsonResponse:
    status: int
    url: str
    content_type: str
    data: Any | None
    text_head: str


class ReleaseGoHttpSession:
    def __init__(self, config: ReleaseGoConfig, timeout: int = DEFAULT_TIMEOUT):
        self.config = config
        self.base_url = config.releasego_base_url.rstrip("/")
        self.timeout = timeout
        https_origin(self.base_url)
        self.redactor = Redactor((config.username, config.password))
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar), SameOriginRedirectHandler(self.base_url))

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = self.base_url + "/" + path.lstrip("/")
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            separator = "&" if "?" in url else "?"
            url = url + separator + query
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> JsonResponse:
        data = None
        request_headers = {
            "User-Agent": "Mozilla/5.0 ReleaseGoShare/1.0",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }
        if headers:
            request_headers.update(headers)
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

        req = urllib.request.Request(require_same_origin(self._url(path, params), self.base_url), data=data, headers=request_headers, method=method.upper())
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
            raise SystemExit("HTTPS request failed; check the configured TLS endpoint, certificate trust and network. HTTP fallback is disabled.") from None

        text = raw.decode("utf-8", errors="replace")
        parsed = None
        if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        return JsonResponse(status=status, url=final_url, content_type=content_type, data=parsed, text_head=self.redactor.text(text)[:300])

    @staticmethod
    def is_unauthenticated(response: JsonResponse) -> bool:
        if response.status in {401, 403}:
            return True
        lowered_url = response.url.lower()
        if lowered_url.endswith("/login") or "/login?" in lowered_url:
            return True
        if response.data is None and "<form" in response.text_head.lower() and "password" in response.text_head.lower():
            return True
        return False

    def login(self) -> JsonResponse:
        if not self.config.username or not self.config.password:
            raise SystemExit("Missing Tingyun credentials. Configure config.local.json or environment variables.")

        self._request("GET", "/login", headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
        response = self._request(
            "POST",
            "/doLogin",
            json_body={"username": self.config.username, "password": self.config.password},
            headers={"Referer": self.base_url + "/login"},
        )
        if response.status != 200:
            raise SystemExit(f"ReleaseGo login failed: HTTP {response.status}")
        if not isinstance(response.data, dict) or response.data.get("code") != 200:
            safe = self.redactor.json(response.data)
            raise SystemExit(f"ReleaseGo login failed: unexpected response {safe}")
        return response

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        retry_login: bool = True,
    ) -> JsonResponse:
        response = self._request(method, path, params=params, json_body=json_body, headers={"Referer": self.base_url + "/"})
        if retry_login and self.is_unauthenticated(response):
            self.login()
            response = self._request(method, path, params=params, json_body=json_body, headers={"Referer": self.base_url + "/"})
        if response.data is None:
            raise SystemExit(f"Expected JSON but received HTTP {response.status} {response.content_type}: {self.redactor.text(response.text_head)!r}")
        return response

    def release_list(self, release_version: str = "", page: int = 1, limit: int = 100) -> JsonResponse:
        return self.request_json(
            "GET",
            "/view/release/getReleaseList",
            params={
                "page": page,
                "limit": limit,
                "releaseVersion": release_version,
                "status": "",
                "releaseForkName": "",
            },
        )

    def config_list(self, release_version_id: int, page: int = 1, limit: int = 200) -> JsonResponse:
        return self.request_json("GET", "/view/release/getReleaseConfigList", params={"releaseVersionId": release_version_id, "page": page, "limit": limit})

    def application_list(self, release_version_id: int, page: int = 1, limit: int = 200) -> JsonResponse:
        return self.request_json("GET", "/view/application/getApplicationList", params={"releaseVersionId": release_version_id, "page": page, "limit": limit})

    def plan_list(self, release_version_id: int, page: int = 1, limit: int = 200) -> JsonResponse:
        return self.request_json("GET", "/view/plan/getPlanList", params={"releaseVersionId": release_version_id, "page": page, "limit": limit})

    def product_list(self) -> JsonResponse:
        return self.request_json("GET", "/view/application/getProductList")

    def applications_by_product(self, product_code: str) -> JsonResponse:
        return self.request_json("GET", "/view/application/getApplicationListByProduct", params={"productCode": product_code})

    def application_versions(self, application_id: str) -> JsonResponse:
        return self.request_json("GET", "/view/application/getApplicationVersionListByApplicationId", params={"applicationId": application_id})

    def application_build_ids(self, application_version_id: str) -> JsonResponse:
        return self.request_json("GET", "/view/application/getApplicationBuildIdListByApplicationId", params={"buildId": application_version_id})

    def save_config(self, row_id: int, release_version_id: int, git_id: str, git_tag: str) -> JsonResponse:
        return self.request_json(
            "POST",
            "/view/release/SaveOrUpdateReleaseConfig",
            json_body={"id": row_id, "releaseVersionId": release_version_id, "gitId": git_id, "gitTag": git_tag},
        )

    def save_plan(self, release_version_id: int, product: str) -> JsonResponse:
        self._product_code(product)
        before = self.plan_list(release_version_id)
        if self._matching_plans(before, release_version_id, product):
            return before
        issue = ""
        try:
            result = self.request_json("POST", "/view/plan/savePlan", json_body={"releaseVersionId": release_version_id, "product": product})
            self._checked(result, "save plan")
            issue = self._response_detail(result)
        except (SystemExit, Exception) as exc:
            issue = self._failure_detail(exc)
        try:
            after = self.plan_list(release_version_id)
            visible = self._matching_plans(after, release_version_id, product)
        except (SystemExit, Exception) as exc:
            raise SystemExit(f"Plan save/readback unverified: {issue}; {self._failure_detail(exc)}") from None
        if not visible:
            raise SystemExit(f"Plan save was not verified: no visible matching plan. Stop; do not delete applications. {issue}")
        return after

    def _response_detail(self, response: JsonResponse) -> str:
        body = response.data if isinstance(response.data, dict) else {}
        return self.redactor.text(f"HTTP={response.status} code={body.get('code')} msg={body.get('msg')}")

    def _failure_detail(self, exc: BaseException) -> str:
        return self.redactor.text(f"{type(exc).__name__}: {exc}")

    def _checked(self, response: JsonResponse, operation: str, rows: bool = False) -> Any:
        if (response.status != 200 or not isinstance(response.data, dict)
                or type(response.data.get("code")) is not int
                or response.data["code"] != 200):
            raise SystemExit(f"{operation}: invalid HTTP/business response; {self._response_detail(response)}; stopped.")
        data = response.data.get("data")
        if rows and (not isinstance(data, list) or any(not isinstance(r, dict) for r in data)):
            raise SystemExit(f"{operation}: invalid data rows; {self._response_detail(response)}; stopped.")
        return data

    def _product_code(self, code: str) -> None:
        rows = self._checked(self.product_list(), "product directory", rows=True)
        if not code or len([r for r in rows if r.get("code") == code]) != 1:
            raise SystemExit("Expected one exact product code from product-list (display names are not codes).")

    def _matching_plans(self, response: JsonResponse, release_id: int, code: str) -> list[dict]:
        rows = self._checked(response, "plan list", rows=True)
        if len(rows) >= 200:
            raise SystemExit("Plan page may be truncated; unique identity cannot be verified.")
        matches = [r for r in rows if r.get("product") == code]
        if (len(matches) > 1 or any(str(r.get("releaseVersionId")) != str(release_id)
                                  or not r.get("id") for r in matches)):
            raise SystemExit("Plan identity is ambiguous or belongs to another release; stopped.")
        return matches

    def _replacement_context(self, name: str, release_id: int, code: str) -> None:
        releases = self._checked(self.release_list(name), "release list", rows=True)
        if len(releases) >= 100:
            raise SystemExit("Release page may be truncated; unique identity cannot be verified.")
        matches = [r for r in releases if r.get("releaseVersion") == name]
        if (len(matches) != 1 or str(matches[0].get("id")) != str(release_id)
                or str(matches[0].get("status")) != "0"):
            raise SystemExit("Exact release name/ID/status=0 verification failed; stopped.")
        if not self._matching_plans(self.plan_list(release_id), release_id, code):
            raise SystemExit("No visible matching product plan; stopped before application deletion.")

    @staticmethod
    def _identity(row: dict, *keys: str) -> str:
        values = {str(row[k]) for k in keys if row.get(k) is not None and str(row[k]) != ""}
        if len(values) != 1:
            raise SystemExit("Missing or conflicting metadata identity; stopped.")
        return values.pop()

    def _version_build(self, app: str, version: str, number: str) -> dict:
        versions = self._checked(self.application_versions(app), "application versions", rows=True)
        matches = [r for r in versions if self._identity(r, "id", "applicationVersionId") == version]
        if len(matches) != 1:
            raise SystemExit("Application version is missing or ambiguous; stopped.")
        selected = matches[0]
        if selected.get("applicationId") is not None and selected["applicationId"] != app:
            raise SystemExit("Application version ownership mismatch; stopped.")
        builds = self._checked(self.application_build_ids(version), "application builds", rows=True)
        candidates = [r for r in builds if str(r.get("buildNumber")) == str(number)]
        if len(candidates) != 1:
            raise SystemExit("Build number is missing or ambiguous; stopped.")
        build = candidates[0]
        if build.get("applicationVersionId") is not None and build["applicationVersionId"] != version:
            raise SystemExit("Build version mismatch; stopped.")
        tag = self._identity(selected, "scmTag", "gitTag")
        if self._identity(build, "buildTag", "scmTag", "gitTag") != tag:
            raise SystemExit("Build tag mismatch; stopped.")
        version_commit = [selected[k] for k in ("gitCommitId", "commitId") if selected.get(k)]
        build_commit = [build[k] for k in ("buildCommitId", "gitCommitId", "commitId") if build.get(k)]
        if len(set(version_commit + build_commit)) > 1:
            raise SystemExit("Build commit mismatch; stopped.")
        return {"scmTag": tag, **{k: build[k] for k in ("buildPackageName", "buildPackageRepoPath", "buildImageId") if build.get(k)}}

    def _application_rows(self, release_id: int, app: str, code: str) -> list[dict]:
        rows = self._checked(self.application_list(release_id), "application list", rows=True)
        if len(rows) >= 200:
            raise SystemExit("Application page may be truncated; unique identity cannot be verified.")
        matches = [r for r in rows if r.get("applicationId") == app]
        if (len(matches) > 1 or any(str(r.get("releaseVersionId")) != str(release_id)
                                  or r.get("productCode") != code
                                  or not r.get("releaseApplicationsId") for r in matches)):
            raise SystemExit("Application row identity/ownership is ambiguous; stopped.")
        return matches

    @staticmethod
    def _target_matches(row: dict, target: dict, metadata: dict) -> bool:
        return (row.get("applicationVersionId") == target["application_version_id"]
                and str(row.get("buildNumber")) == str(target["build_number"])
                and all(row.get(k) == v for k, v in metadata.items()))

    def replace_application(self, release_version: str, release_version_id: int,
                            product_code: str, application_id: str,
                            application_version_id: str, build_number: str,
                            backup: Path) -> dict[str, Any]:
        """Guard a non-atomic delete/save with readback and at most one restoration.

        API writes still require caller authorization. The server offers no CAS or
        transaction: concurrent writers must be excluded operationally.
        """
        self._product_code(product_code)
        apps = self._checked(self.applications_by_product(product_code), "product applications", rows=True)
        matches = [r for r in apps if self._identity(r, "id", "applicationId") == application_id]
        if len(matches) != 1 or self._identity(matches[0], "product", "productCode") != product_code:
            raise SystemExit("Application product ownership mismatch; stopped.")
        self._replacement_context(release_version, release_version_id, product_code)
        target = dict(release_version_id=release_version_id, product_code=product_code,
                      application_id=application_id, application_version_id=application_version_id,
                      build_number=str(build_number))
        metadata = self._version_build(application_id, application_version_id, str(build_number))
        rows = self._application_rows(release_version_id, application_id, product_code)
        old = rows[0] if rows else None
        if old and self._target_matches(old, target, metadata):
            return {"status": "unchanged"}
        restore = None
        old_metadata = None
        if old:
            restore = {**target, "application_version_id": self._identity(old, "applicationVersionId"),
                       "build_number": self._identity(old, "buildNumber")}
            old_metadata = self._version_build(application_id, restore["application_version_id"], restore["build_number"])
            if not self._target_matches(old, restore, old_metadata):
                raise SystemExit("Old row does not match recoverable build metadata; stopped.")
        backup = Path(backup).expanduser().resolve()
        snapshot = {"releaseVersion": release_version, "oldRowId": old["releaseApplicationsId"] if old else None,
                    "restore": restore, "target": target}
        serialized = json.dumps(snapshot, ensure_ascii=False, indent=2)
        safe = self.redactor.text(serialized)
        if safe != serialized:
            raise SystemExit("Backup contains sensitive values; stopped before writing.")
        try:
            with backup.open("x", encoding="utf-8") as stream:
                stream.write(safe + "\n")
        except OSError:
            raise SystemExit("Backup could not be exclusively created; stopped before deletion.") from None
        self._replacement_context(release_version, release_version_id, product_code)
        if self._application_rows(release_version_id, application_id, product_code) != rows:
            raise SystemExit("Application changed during validation; stopped before deletion.")
        issues = []
        if old:
            try:
                self._checked(self.delete_application(old["releaseApplicationsId"], release_version_id), "delete application")
            except (SystemExit, Exception) as exc:
                issues.append(self._failure_detail(exc))
            try:
                current = self._application_rows(release_version_id, application_id, product_code)
            except (SystemExit, Exception) as exc:
                issues.append(self._failure_detail(exc))
                raise SystemExit(f"Delete outcome unknown; no further writes. Inspect row and backup: {backup}; {'; '.join(issues)}") from None
            if current:
                state = "old row retained" if current == rows else "row present but unexpected"
                raise SystemExit(f"Delete not verified: {state}; no further writes. Backup: {backup}; {'; '.join(issues)}")
            # A timed-out delete may have committed. With absence verified, resume
            # the authorized save once, only while its release and plan remain valid.
            try:
                self._replacement_context(release_version, release_version_id, product_code)
            except (SystemExit, Exception) as exc:
                issues.append(self._failure_detail(exc))
                raise SystemExit(f"Delete verified but save blocked: row missing; backup: {backup}; {'; '.join(issues)}") from None
        # Do not repeat a timed-out write: read the server first.
        try:
            self._checked(self.save_application(**target), "save application")
        except (SystemExit, Exception) as exc:
            issues.append(self._failure_detail(exc))
        try:
            current = self._application_rows(release_version_id, application_id, product_code)
        except (SystemExit, Exception) as exc:
            issues.append(self._failure_detail(exc))
            raise SystemExit(f"Save outcome unknown; no restoration attempted. Inspect row and backup: {backup}; {'; '.join(issues)}") from None
        if len(current) == 1 and self._target_matches(current[0], target, metadata):
            return {"status": "replaced" if old else "added", "backup": str(backup), "diagnostics": issues}
        if current:
            raise SystemExit(f"Save verification failed; row present but unexpected, no further writes. Inspect backup: {backup}; {'; '.join(issues)}")
        if restore:
            try:
                self._replacement_context(release_version, release_version_id, product_code)
                if self._application_rows(release_version_id, application_id, product_code):
                    raise SystemExit("Row appeared before restoration")
                self._checked(self.save_application(**restore), "restore application")
            except (SystemExit, Exception) as exc:
                issues.append(self._failure_detail(exc))
            try:
                current = self._application_rows(release_version_id, application_id, product_code)
            except (SystemExit, Exception) as exc:
                issues.append(self._failure_detail(exc))
                raise SystemExit(f"Restoration outcome unknown; inspect row and backup: {backup}; {'; '.join(issues)}") from None
            if len(current) == 1 and self._target_matches(current[0], restore, old_metadata):
                raise SystemExit(f"New application save failed; old row restored. Backup: {backup}; {'; '.join(issues)}")
        state = "row present but unexpected" if current else "row missing"
        raise SystemExit(f"Application save/restoration failed: {state}; inspect backup: {backup}; {'; '.join(issues)}")

    def confirm_plan(self, plan_id: int) -> JsonResponse:
        return self.request_json("POST", "/view/plan/updateProductStatus", json_body={"id": plan_id})

    def save_application(
        self,
        release_version_id: int,
        product_code: str,
        application_id: str,
        application_version_id: str,
        build_number: str,
        row_id: int | None = None,
    ) -> JsonResponse:
        body: dict[str, Any] = {
            "releaseVersionId": release_version_id,
            "productCode": product_code,
            "applicationId": application_id,
            "applicationVersionId": application_version_id,
            "buildNumber": build_number,
        }
        if row_id is not None:
            body["id"] = row_id
        return self.request_json("POST", "/view/application/saveOrUpdateReleaseApplications", json_body=body)

    def delete_application(self, row_id: int, release_version_id: int) -> JsonResponse:
        return self.request_json("POST", "/view/application/delReleaseApplication", json_body={"id": row_id, "releaseVersionId": release_version_id})




def print_json(value: Any) -> None:
    print(safe_json(value))


def response_rows(response: JsonResponse) -> list[Any]:
    if isinstance(response.data, dict) and isinstance(response.data.get("data"), list):
        return response.data["data"]
    return []


def summary_response(response: JsonResponse) -> dict[str, Any]:
    rows = response_rows(response)
    first = rows[0] if rows and isinstance(rows[0], dict) else None
    return {
        "httpStatus": response.status,
        "code": response.data.get("code") if isinstance(response.data, dict) else None,
        "msg": response.data.get("msg") if isinstance(response.data, dict) else None,
        "count": response.data.get("count") if isinstance(response.data, dict) else None,
        "rows": len(rows),
        "firstKeys": sorted(first.keys()) if first else None,
    }


def require_write_confirmation(value: str) -> None:
    if value != "yes":
        raise SystemExit("This command writes to ReleaseGo. Re-run with --confirm-write yes after verifying all arguments.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Use ReleaseGo APIs without browser automation.")
    parser.add_argument("--skill-root", type=Path, help="Skill root directory for config.local.json lookup.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    sub = parser.add_subparsers(dest="command", required=True)

    login_test = sub.add_parser("login-test", help="Login and optionally probe a release list API.")
    login_test.add_argument("--probe-release-version", default="", help="Optional release version to query after login.")

    release_list = sub.add_parser("release-list", help="Query ReleaseGo release list.")
    release_list.add_argument("--release-version", default="", help="Release version filter.")
    release_list.add_argument("--page", type=int, default=1)
    release_list.add_argument("--limit", type=int, default=100)
    release_list.add_argument("--summary", action="store_true", help="Print only safe summary fields.")

    for command, help_text in [
        ("config-list", "Query ReleaseGo config rows."),
        ("app-list", "Query ReleaseGo application rows."),
        ("plan-list", "Query ReleaseGo participating product-line rows."),
    ]:
        parser_item = sub.add_parser(command, help=help_text)
        parser_item.add_argument("--release-version-id", type=int, required=True)
        parser_item.add_argument("--page", type=int, default=1)
        parser_item.add_argument("--limit", type=int, default=200)
        parser_item.add_argument("--summary", action="store_true")

    product_list = sub.add_parser("product-list", help="Query ReleaseGo product lines.")
    product_list.add_argument("--summary", action="store_true")

    apps_by_product = sub.add_parser("apps-by-product", help="Query application definitions by product code.")
    apps_by_product.add_argument("--product-code", required=True)
    apps_by_product.add_argument("--summary", action="store_true")

    versions = sub.add_parser("application-versions", help="Query application versions by application id.")
    versions.add_argument("--application-id", required=True)
    versions.add_argument("--summary", action="store_true")

    build_ids = sub.add_parser("application-build-ids", help="Query ReleaseGo Build ID rows by applicationVersionId.")
    build_ids.add_argument("--application-version-id", required=True)
    build_ids.add_argument("--summary", action="store_true")

    save_config = sub.add_parser("save-config", help="Update one ReleaseGo config row. This has side effects.")
    save_config.add_argument("--id", type=int, required=True)
    save_config.add_argument("--release-version-id", type=int, required=True)
    save_config.add_argument("--git-id", required=True)
    save_config.add_argument("--git-tag", required=True)
    save_config.add_argument("--confirm-write", choices=["yes"], required=True)

    add_plan = sub.add_parser("add-plan", help="Add one participating product line. This has side effects.")
    add_plan.add_argument("--release-version-id", type=int, required=True)
    add_plan.add_argument("--product", required=True)
    add_plan.add_argument("--confirm-write", choices=["yes"], required=True)

    confirm_plan = sub.add_parser("confirm-plan", help="Confirm a participating product-line row. This has side effects.")
    confirm_plan.add_argument("--plan-id", type=int, required=True)
    confirm_plan.add_argument("--confirm-write", choices=["yes"], required=True)

    save_app = sub.add_parser("save-app", help="Save one ReleaseGo application row. This has side effects.")
    save_app.add_argument("--release-version-id", type=int, required=True)
    save_app.add_argument("--product-code", required=True)
    save_app.add_argument("--application-id", required=True)
    save_app.add_argument("--application-version-id", required=True)
    save_app.add_argument("--build-number", required=True)
    save_app.add_argument("--id", type=int)
    save_app.add_argument("--confirm-write", choices=["yes"], required=True)

    replace_app = sub.add_parser("replace-app", help="Safely replace an application with validation, exclusive backup and readback.")
    replace_app.add_argument("--release-version", required=True)
    replace_app.add_argument("--release-version-id", type=int, required=True)
    replace_app.add_argument("--product-code", required=True)
    replace_app.add_argument("--application-id", required=True)
    replace_app.add_argument("--application-version-id", required=True)
    replace_app.add_argument("--build-number", required=True)
    replace_app.add_argument("--backup", type=Path, required=True)
    replace_app.add_argument("--confirm-write", choices=["yes"], required=True)

    delete_app = sub.add_parser("delete-app", help="Delete one ReleaseGo application row. This has side effects.")
    delete_app.add_argument("--id", type=int, required=True)
    delete_app.add_argument("--release-version-id", type=int, required=True)
    delete_app.add_argument("--confirm-write", choices=["yes"], required=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    cfg = load_config(args.skill_root, require_credentials=True)
    session = ReleaseGoHttpSession(cfg, timeout=args.timeout)
    def print_json(value: Any) -> None:
        print(session.redactor.json(value))

    if args.command == "login-test":
        login = session.login()
        output: dict[str, Any] = {
            "login": {
                "httpStatus": login.status,
                "code": login.data.get("code") if isinstance(login.data, dict) else None,
                "msg": login.data.get("msg") if isinstance(login.data, dict) else None,
                "credentialSource": cfg.credential_source,
                "hasUsername": bool(cfg.username),
                "hasPassword": bool(cfg.password),
            }
        }
        if args.probe_release_version:
            probe = session.release_list(args.probe_release_version, page=1, limit=1)
            rows = probe.data.get("data", []) if isinstance(probe.data, dict) else []
            output["probe"] = {
                "httpStatus": probe.status,
                "code": probe.data.get("code") if isinstance(probe.data, dict) else None,
                "msg": probe.data.get("msg") if isinstance(probe.data, dict) else None,
                "count": probe.data.get("count") if isinstance(probe.data, dict) else None,
                "rows": len(rows) if isinstance(rows, list) else None,
            }
        print_json(output)
        return 0

    if args.command == "release-list":
        response = session.release_list(args.release_version, page=args.page, limit=args.limit)
        if args.summary and isinstance(response.data, dict):
            rows = response.data.get("data", [])
            print_json(
                {
                    "httpStatus": response.status,
                    "code": response.data.get("code"),
                    "msg": response.data.get("msg"),
                    "count": response.data.get("count"),
                    "rows": len(rows) if isinstance(rows, list) else None,
                }
            )
        else:
            print_json(response.data)
        return 0

    if args.command in {"config-list", "app-list", "plan-list"}:
        method = {"config-list": session.config_list, "app-list": session.application_list, "plan-list": session.plan_list}[args.command]
        response = method(args.release_version_id, page=args.page, limit=args.limit)
        print_json(summary_response(response) if args.summary else response.data)
        return 0

    if args.command == "product-list":
        response = session.product_list()
        print_json(summary_response(response) if args.summary else response.data)
        return 0

    if args.command == "apps-by-product":
        response = session.applications_by_product(args.product_code)
        print_json(summary_response(response) if args.summary else response.data)
        return 0

    if args.command == "application-versions":
        response = session.application_versions(args.application_id)
        print_json(summary_response(response) if args.summary else response.data)
        return 0

    if args.command == "application-build-ids":
        response = session.application_build_ids(args.application_version_id)
        print_json(summary_response(response) if args.summary else response.data)
        return 0

    if args.command == "save-config":
        require_write_confirmation(args.confirm_write)
        print_json(session.save_config(args.id, args.release_version_id, args.git_id, args.git_tag).data)
        return 0

    if args.command == "add-plan":
        require_write_confirmation(args.confirm_write)
        print_json(session.save_plan(args.release_version_id, args.product).data)
        return 0

    if args.command == "confirm-plan":
        require_write_confirmation(args.confirm_write)
        print_json(session.confirm_plan(args.plan_id).data)
        return 0

    if args.command == "save-app":
        require_write_confirmation(args.confirm_write)
        print_json(
            session.save_application(
                args.release_version_id,
                args.product_code,
                args.application_id,
                args.application_version_id,
                args.build_number,
                args.id,
            ).data
        )
        return 0

    if args.command == "replace-app":
        require_write_confirmation(args.confirm_write)
        session.login()
        print_json(session.replace_application(args.release_version, args.release_version_id,
                   args.product_code, args.application_id, args.application_version_id,
                   args.build_number, args.backup))
        return 0

    if args.command == "delete-app":
        require_write_confirmation(args.confirm_write)
        print_json(session.delete_application(args.id, args.release_version_id).data)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
