#!/usr/bin/env python3
"""Browserless HTTP client for the Tingyun Chandao (ZenTao Pro) instance."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener


DEFAULT_BASE_URL = "https://chandao.tingyun.com/pro/"
LOGIN_PAGE = "user-login.html"
LOGIN_ENDPOINT = "user-login.json"
SESSION_FILE_NAME = "chandao-http-cookies.txt"


class ChandaoError(RuntimeError):
    """Base error for an operation that did not complete."""


class ConfigurationError(ChandaoError):
    """Credentials or local configuration are missing."""


class AuthenticationError(ChandaoError):
    """The current session could not authenticate."""


class SafetyError(ChandaoError):
    """A requested write does not meet the explicit safety policy."""


class ProtocolError(ChandaoError):
    """The server response does not match a verified Chandao contract."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    url: str
    headers: Mapping[str, str]
    body: str


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        data: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse: ...


class UrlLibTransport:
    """Cookie-persisting transport that depends only on the Python standard library."""

    def __init__(self, cookie_file: Path, timeout_seconds: int = 30):
        self.cookie_file = cookie_file
        self.timeout_seconds = timeout_seconds
        self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
        self.cookies = MozillaCookieJar(str(cookie_file))
        if cookie_file.exists():
            try:
                self.cookies.load(ignore_discard=True, ignore_expires=True)
            except (OSError, ValueError):
                cookie_file.unlink(missing_ok=True)
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))

    def request(
        self,
        method: str,
        url: str,
        data: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        encoded_data = None
        merged_headers = {"User-Agent": "chandao-skill-api/1.0"}
        if headers:
            merged_headers.update(headers)
        if data is not None:
            encoded_data = urlencode(data).encode("utf-8")
            merged_headers.setdefault(
                "Content-Type", "application/x-www-form-urlencoded; charset=UTF-8"
            )
        request = Request(url, data=encoded_data, headers=merged_headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
                result = HttpResponse(
                    status=response.status,
                    url=response.geturl(),
                    headers=dict(response.headers.items()),
                    body=body,
                )
        except HTTPError as error:
            result = HttpResponse(
                status=error.code,
                url=error.geturl(),
                headers=dict(error.headers.items()) if error.headers else {},
                body=error.read().decode("utf-8", errors="replace"),
            )
        except URLError as error:
            raise ChandaoError(f"Chandao HTTP request failed: {error.reason}") from error
        self.cookies.save(ignore_discard=True, ignore_expires=True)
        return result


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict[str, str]] = []
        self._anchor: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            values = {name: value or "" for name, value in attrs}
            self._anchor = {"href": values.get("href", ""), "title": values.get("title", ""), "text": ""}

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor is not None:
            self._anchor["text"] = " ".join(self._anchor["text"].split())
            self.anchors.append(self._anchor)
            self._anchor = None


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class _BugResolveFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inputs: dict[str, str] = {}
        self.options: dict[str, dict[str, str]] = {}
        self.selected: dict[str, str] = {}
        self.textareas: set[str] = set()
        self._select_name: str | None = None
        self._option_value: str | None = None
        self._option_selected = False
        self._option_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag == "input" and values.get("name"):
            self.inputs[values["name"]] = values.get("value", "")
        elif tag == "select":
            self._select_name = values.get("name") or None
            if self._select_name:
                self.options.setdefault(self._select_name, {})
        elif tag == "option" and self._select_name:
            self._option_value = values.get("value", "")
            self._option_selected = "selected" in values
            self._option_text = []
        elif tag == "textarea" and values.get("name"):
            self.textareas.add(values["name"])

    def handle_data(self, data: str) -> None:
        if self._option_value is not None:
            self._option_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self._option_value is not None and self._select_name:
            text = " ".join(" ".join(self._option_text).split())
            self.options[self._select_name][self._option_value] = text
            if self._option_selected:
                self.selected[self._select_name] = self._option_value
            self._option_value = None
            self._option_selected = False
            self._option_text = []
        elif tag == "select":
            self._select_name = None


@dataclass(frozen=True)
class _BugResolveForm:
    status: str
    resolved_date: str
    assigned_to: str
    resolution_options: Mapping[str, str]
    resolved_build_options: Mapping[str, str]
    has_comment: bool


def _html_text(source: str) -> str:
    parser = _TextParser()
    parser.feed(source)
    return " ".join(" ".join(parser.parts).split())


def _anchors(source: str) -> list[dict[str, str]]:
    parser = _AnchorParser()
    parser.feed(source)
    return parser.anchors


def _value_after_label(source: str, label: str) -> str:
    pattern = rf"<th[^>]*>\s*{re.escape(label)}\s*</th>\s*<td[^>]*>(.*?)</td>"
    match = re.search(pattern, source, flags=re.IGNORECASE | re.DOTALL)
    return _html_text(match.group(1)) if match else ""


def _page_title(source: str) -> str:
    match = re.search(r"<title>(.*?)</title>", source, flags=re.IGNORECASE | re.DOTALL)
    return _html_text(match.group(1)) if match else ""


def _detail_content_after_title(source: str, label: str) -> str:
    pattern = (
        rf"<div[^>]*class=['\"][^'\"]*detail-title[^'\"]*['\"][^>]*>\s*"
        rf"{re.escape(label)}\s*</div>\s*"
        rf"<div[^>]*class=['\"][^'\"]*detail-content[^'\"]*['\"][^>]*>(.*?)</div>"
    )
    match = re.search(pattern, source, flags=re.IGNORECASE | re.DOTALL)
    return _html_text(match.group(1)) if match else ""


def _parse_bug_resolve_form(source: str) -> _BugResolveForm:
    parser = _BugResolveFormParser()
    parser.feed(source)
    status = parser.inputs.get("status", "")
    resolved_date = parser.inputs.get("resolvedDate", "")
    assigned_to = parser.selected.get("assignedTo", "")
    resolution_options = parser.options.get("resolution", {})
    resolved_build_options = parser.options.get("resolvedBuild", {})
    if status != "resolved" or not resolved_date or not assigned_to:
        raise ProtocolError("Chandao Bug resolve form no longer exposes the required status/date/assignee fields.")
    if not resolution_options or not resolved_build_options:
        raise ProtocolError("Chandao Bug resolve form no longer exposes resolution or resolved-build options.")
    return _BugResolveForm(
        status=status,
        resolved_date=resolved_date,
        assigned_to=assigned_to,
        resolution_options=resolution_options,
        resolved_build_options=resolved_build_options,
        has_comment="comment" in parser.textareas,
    )


class ChandaoClient:
    def __init__(
        self,
        workspace: Path,
        username: str | None = None,
        password: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        transport: Transport | None = None,
    ):
        self.workspace = workspace.resolve()
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/") + "/"
        self.session_dir = self.workspace / ".chandao-session"
        self.session_file = self.session_dir / SESSION_FILE_NAME
        self.transport = transport or UrlLibTransport(self.session_file)

    @classmethod
    def from_environment(cls, workspace: Path, base_url: str = DEFAULT_BASE_URL) -> "ChandaoClient":
        username = os.environ.get("TINGYUN_USERNAME", "").strip()
        password = os.environ.get("TINGYUN_PASSWORD", "")
        if not username or not password:
            raise ConfigurationError(
                "Missing TINGYUN_USERNAME or TINGYUN_PASSWORD. Configure both environment variables."
            )
        return cls(workspace=workspace, username=username, password=password, base_url=base_url)

    def _url(self, endpoint: str) -> str:
        return urljoin(self.base_url, endpoint.lstrip("/"))

    def _request(
        self, method: str, endpoint: str, data: Mapping[str, str] | None = None
    ) -> HttpResponse:
        response = self.transport.request(method, self._url(endpoint), data=data)
        if response.status >= 400:
            raise ChandaoError(f"Chandao returned HTTP {response.status} for {endpoint}.")
        return response

    @staticmethod
    def _is_login_page(source: str) -> bool:
        lowered = source.lower()
        return (
            '"currentmodule":"user"' in lowered and '"currentmethod":"login"' in lowered
        ) or "\u7528\u6237\u767b\u5f55" in source or "name='verifyrand'" in lowered or bool(
            re.search(r"self\.location\s*=\s*['\"][^'\"]*user-login-", lowered)
        )

    @staticmethod
    def _requires_password_change(source: str) -> bool:
        return bool(
            re.search(r"self\.location\s*=\s*['\"][^'\"]*my-changepassword", source.lower())
        )

    @staticmethod
    def _double_md5(password: str, verify_rand: str) -> str:
        first = hashlib.md5(password.encode("utf-8")).hexdigest()
        return hashlib.md5((first + verify_rand).encode("utf-8")).hexdigest()

    @staticmethod
    def _password_strength(password: str) -> int:
        """Match Chandao's computePasswordStrength() function from my.full.js."""
        if not password:
            return 0
        unique_chars = ""
        complexity: dict[int, int] = {}
        for character in password:
            code = ord(character)
            if 48 <= code <= 57:
                complexity[2] = 2
            elif 65 <= code <= 90:
                complexity[1] = 2
            elif 97 <= code <= 122:
                complexity[0] = 1
            else:
                complexity[3] = 3
            if character not in unique_chars:
                unique_chars += character
        strength = max(0, len(unique_chars) - 4)
        strength += sum(complexity.values()) + 2 * (len(complexity) - 1)
        if len(password) < 6 and strength >= 10:
            strength = 9
        return min(strength, 29) // 10

    def _login(self) -> None:
        if not self.username or not self.password:
            raise ConfigurationError(
                "Credentials are unavailable. Set TINGYUN_USERNAME and TINGYUN_PASSWORD."
            )
        login_page = self._request("GET", LOGIN_PAGE).body
        verify_rand = re.search(r"name='verifyRand'\s+id='verifyRand'\s+value='([^']+)'", login_page)
        if not verify_rand:
            raise ProtocolError("Chandao login page did not provide verifyRand.")
        data = {
            "account": self.username,
            "password": self._double_md5(self.password, verify_rand.group(1)),
            "passwordStrength": str(self._password_strength(self.password)),
            "referer": "/pro/my.html",
            "verifyRand": verify_rand.group(1),
            "keepLogin": "0",
        }
        response = self._request("POST", LOGIN_ENDPOINT, data=data)
        try:
            result = json.loads(response.body)
        except json.JSONDecodeError as error:
            raise ProtocolError("Chandao login endpoint did not return JSON.") from error
        if result.get("status") != "success":
            raise AuthenticationError("Chandao login failed. Check the configured credentials.")
        verification = self._request("GET", "my.html?onlybody=yes")
        if self._requires_password_change(verification.body):
            raise AuthenticationError(
                "Chandao requires a password change. Update the account password outside this skill, then refresh TINGYUN_PASSWORD."
            )
        if self._is_login_page(verification.body):
            raise AuthenticationError("Chandao login did not establish an authenticated session.")

    def _authenticated_request(self, method: str, endpoint: str, data: Mapping[str, str] | None = None) -> HttpResponse:
        response = self._request(method, endpoint, data=data)
        if self._requires_password_change(response.body):
            raise AuthenticationError(
                "Chandao requires a password change. Update the account password outside this skill, then refresh TINGYUN_PASSWORD."
            )
        if not self._is_login_page(response.body):
            return response
        self._login()
        response = self._request(method, endpoint, data=data)
        if self._requires_password_change(response.body):
            raise AuthenticationError(
                "Chandao requires a password change. Update the account password outside this skill, then refresh TINGYUN_PASSWORD."
            )
        if self._is_login_page(response.body):
            raise AuthenticationError("Chandao session remained unauthenticated after one login retry.")
        return response

    @staticmethod
    def _items(source: str, object_type: str) -> list[dict[str, Any]]:
        if object_type == "effort":
            pattern = re.compile(r"/effort-view-(\d+)(?:-[^/?]+)?\.html", flags=re.IGNORECASE)
        else:
            pattern = re.compile(rf"/{object_type}-view-(\d+)\.html", flags=re.IGNORECASE)
        found: dict[int, str] = {}
        for anchor in _anchors(source):
            match = pattern.search(anchor["href"])
            if not match:
                continue
            object_id = int(match.group(1))
            title = html.unescape(anchor["title"] or anchor["text"]).strip()
            if title and not title.isdigit():
                found[object_id] = title
            else:
                found.setdefault(object_id, "")
        return [{"id": key, "title": found[key]} for key in sorted(found, reverse=True)]

    def auth_check(self) -> dict[str, Any]:
        self._authenticated_request("GET", "my.html?onlybody=yes")
        return {
            "authenticated": True,
            "credentialSource": "environment",
            "sessionFile": str(self.session_file),
        }

    def my_bugs(self, scope: str = "assignedTo", limit: int = 20, page: int = 1) -> list[dict[str, Any]]:
        allowed = {"assignedTo", "openedBy", "resolvedBy", "closedBy"}
        if scope not in allowed:
            raise SafetyError(f"Unsupported bug scope: {scope}.")
        if not 1 <= limit <= 200 or page < 1:
            raise SafetyError("Bug limit must be 1..200 and page must be positive.")
        endpoint = f"my-bug-{scope}-id_asc-0-{limit}-{page}.html?onlybody=yes"
        return self._items(self._authenticated_request("GET", endpoint).body, "bug")

    def bug_detail(self, bug_id: int) -> dict[str, Any]:
        if bug_id <= 0:
            raise SafetyError("Bug ID must be positive.")
        source = self._authenticated_request("GET", f"bug-view-{bug_id}.html?onlybody=yes").body
        if re.search(r"history\.back\(-?1\)", source):
            raise ProtocolError(f"Chandao did not expose Bug detail {bug_id} to the current account.")
        title = _page_title(source)
        title_match = re.search(r"BUG\s*#\d+\s+(.+?)\s+-\s+(.+?)\s+-\s+", title, flags=re.IGNORECASE)
        reproduction = re.search(
            r"\u91cd\u73b0\u6b65\u9aa4\s*</div>\s*<div[^>]*>(.*?)</div>", source, flags=re.DOTALL
        )
        severity = _value_after_label(source, "\u4e25\u91cd\u7a0b\u5ea6")
        if not severity:
            severity_match = re.search(
                r"class=['\"][^'\"]*label-severity[^'\"]*['\"][^>]*data-severity=['\"]([^'\"]+)",
                source,
                flags=re.IGNORECASE,
            )
            severity = severity_match.group(1) if severity_match else ""
        return {
            "id": bug_id,
            "title": title_match.group(1).strip() if title_match else title,
            "product": title_match.group(2).strip() if title_match else "",
            "status": _value_after_label(source, "\u0042ug\u72b6\u6001"),
            "severity": severity,
            "priority": _value_after_label(source, "\u4f18\u5148\u7ea7"),
            "reproduction_steps": _html_text(reproduction.group(1)) if reproduction else "",
        }

    def resolve_bug(
        self,
        bug_id: int,
        resolution: str,
        resolved_build: str,
        comment: str | None = None,
        apply: bool = False,
    ) -> dict[str, Any]:
        if not apply:
            raise SafetyError("Refusing to resolve a Bug without --apply.")
        if bug_id <= 0:
            raise SafetyError("Bug ID must be positive.")
        if not resolution or not resolved_build:
            raise SafetyError("Resolution and resolved build are required.")

        endpoint = f"bug-resolve-{bug_id}.html?onlybody=yes"
        form = _parse_bug_resolve_form(self._authenticated_request("GET", endpoint).body)
        if resolution not in form.resolution_options:
            raise SafetyError(f"Unsupported Bug resolution: {resolution}.")
        if resolved_build not in form.resolved_build_options:
            raise SafetyError(f"Unsupported resolved build: {resolved_build}.")
        if comment and not form.has_comment:
            raise ProtocolError("Chandao Bug resolve form no longer exposes the comment field.")

        data = {
            "status": form.status,
            "resolution": resolution,
            "resolvedBuild": resolved_build,
            "resolvedDate": form.resolved_date,
            "assignedTo": form.assigned_to,
        }
        if comment:
            data["comment"] = comment
        result = self._authenticated_request("POST", endpoint, data=data)
        if self._response_failed(result.body):
            raise ChandaoError("Chandao rejected the Bug resolve request.")

        source = self._authenticated_request("GET", f"bug-view-{bug_id}.html?onlybody=yes").body
        status = _value_after_label(source, "\u0042ug\u72b6\u6001")
        resolved_resolution = _value_after_label(source, "\u89e3\u51b3\u65b9\u6848")
        resolved_build_name = _value_after_label(source, "\u89e3\u51b3\u7248\u672c")
        expected_resolution = form.resolution_options[resolution]
        expected_build = form.resolved_build_options[resolved_build]
        if (
            status != "\u5df2\u89e3\u51b3"
            or resolved_resolution != expected_resolution
            or resolved_build_name != expected_build
        ):
            raise ProtocolError("Resolved Bug could not be verified by re-reading status, resolution, and build.")
        return {
            "resolved": True,
            "id": bug_id,
            "status": status,
            "resolution": resolved_resolution,
            "resolvedBuild": resolved_build_name,
            "commentWritten": bool(comment),
        }

    def my_tasks(self, scope: str = "assignedTo", limit: int = 20, page: int = 1) -> list[dict[str, Any]]:
        allowed = {"assignedTo", "openedBy", "finishedBy", "closedBy", "canceledBy"}
        if scope not in allowed:
            raise SafetyError(f"Unsupported task scope: {scope}.")
        if not 1 <= limit <= 200 or page < 1:
            raise SafetyError("Task limit must be 1..200 and page must be positive.")
        endpoint = f"my-task-{scope}-id_asc-0-{limit}-{page}.html?onlybody=yes"
        return self._items(self._authenticated_request("GET", endpoint).body, "task")

    def task_detail(self, task_id: int) -> dict[str, Any]:
        if task_id <= 0:
            raise SafetyError("Task ID must be positive.")
        source = self._authenticated_request("GET", f"task-view-{task_id}.html?onlybody=yes").body
        if re.search(r"history\.back\(-?1\)", source):
            raise ProtocolError(f"Chandao did not expose task detail {task_id} to the current account.")
        page_title = _page_title(source)
        title_match = re.search(r"TASK\s*#\d+\s+(.+?)\s+/\s+", page_title, flags=re.IGNORECASE)
        return {
            "id": task_id,
            "title": title_match.group(1).strip() if title_match else page_title,
            "project": _value_after_label(source, "\u6240\u5c5e\u9879\u76ee"),
            "module": _value_after_label(source, "\u6240\u5c5e\u6a21\u5757"),
            "story": _value_after_label(source, "\u76f8\u5173\u9700\u6c42"),
            "assignee": _value_after_label(source, "\u6307\u6d3e\u7ed9"),
            "type": _value_after_label(source, "\u4efb\u52a1\u7c7b\u578b"),
            "status": _value_after_label(source, "\u4efb\u52a1\u72b6\u6001"),
            "progress": _value_after_label(source, "\u8fdb\u5ea6"),
            "priority": _value_after_label(source, "\u4f18\u5148\u7ea7"),
            "estimate": _value_after_label(source, "\u6700\u521d\u9884\u8ba1"),
            "consumed": _value_after_label(source, "\u603b\u8ba1\u6d88\u8017"),
            "left": _value_after_label(source, "\u9884\u8ba1\u5269\u4f59"),
            "est_started": _value_after_label(source, "\u9884\u8ba1\u5f00\u59cb"),
            "real_started": _value_after_label(source, "\u5b9e\u9645\u5f00\u59cb"),
            "deadline": _value_after_label(source, "\u622a\u6b62\u65e5\u671f"),
            "description": _detail_content_after_title(source, "\u4efb\u52a1\u63cf\u8ff0"),
            "story_description": _detail_content_after_title(source, "\u9700\u6c42\u63cf\u8ff0"),
            "acceptance": _detail_content_after_title(source, "\u9a8c\u6536\u6807\u51c6"),
        }

    def my_efforts(self, scope: str = "all") -> list[dict[str, Any]]:
        allowed = {"all", "thisweek", "lastweek", "thismonth", "lastmonth"}
        if scope not in allowed:
            raise SafetyError(f"Unsupported effort scope: {scope}.")
        source = self._authenticated_request("GET", f"my-effort-{scope}.html?onlybody=yes").body
        return self._items(source, "effort")

    def calendar_efforts(self, year: int) -> list[dict[str, Any]]:
        if not 2000 <= year <= 2100:
            raise SafetyError("Calendar year must be between 2000 and 2100.")
        calendar = self._authenticated_request("GET", "effort-calendar.html?onlybody=yes").body
        endpoint_match = re.search(r"effort-ajaxGetEfforts-(\d+)-\{year\}\.html", calendar)
        if not endpoint_match:
            raise ProtocolError("Chandao effort calendar did not expose the account/year endpoint.")
        endpoint = f"effort-ajaxGetEfforts-{endpoint_match.group(1)}-{year}.html?onlybody=yes"
        response = self._authenticated_request("GET", endpoint).body
        try:
            events = json.loads(response)
        except json.JSONDecodeError as error:
            raise ProtocolError("Chandao effort calendar endpoint did not return JSON.") from error
        if not isinstance(events, list):
            raise ProtocolError("Chandao effort calendar JSON is not an event list.")
        return events

    def effort_detail(self, effort_id: int) -> dict[str, Any]:
        if effort_id <= 0:
            raise SafetyError("Effort ID must be positive.")
        source = self._authenticated_request("GET", f"effort-view-{effort_id}.html?onlybody=yes").body
        object_match = re.search(r"/(task|bug)-view-(\d+)\.html", source, flags=re.IGNORECASE)
        return {
            "id": effort_id,
            "date": _value_after_label(source, "\u65e5\u671f"),
            "consumed": _value_after_label(source, "\u8017\u65f6"),
            "left": _value_after_label(source, "\u5269\u4f59"),
            "work": _value_after_label(source, "\u5de5\u4f5c\u5185\u5bb9"),
            "objectType": object_match.group(1) if object_match else "",
            "objectID": int(object_match.group(2)) if object_match else 0,
        }

    @staticmethod
    def _validate_effort(
        object_type: str, object_id: int, effort_date: str, consumed: float, work: str
    ) -> None:
        if object_type not in {"task", "bug"}:
            raise SafetyError("Effort object type must be task or bug.")
        if object_id <= 0:
            raise SafetyError("Effort object ID must be positive.")
        try:
            parsed_date = date.fromisoformat(effort_date)
        except ValueError as error:
            raise SafetyError("Effort date must use YYYY-MM-DD.") from error
        if parsed_date > date.today():
            raise SafetyError("Future dates cannot receive effort logs.")
        if consumed <= 0 or consumed > 4:
            raise SafetyError("A single effort log must be greater than 0 and at most 4 hours.")
        if not work.strip():
            raise SafetyError("Effort work content is required.")

    @staticmethod
    def _hours(value: str) -> float | None:
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:\u5c0f\u65f6)?\s*", value)
        return float(match.group(1)) if match else None

    def _find_duplicate(self, effort_date: str, consumed: float, work: str) -> dict[str, Any] | None:
        target_hours = float(consumed)
        for event in self.calendar_efforts(date.fromisoformat(effort_date).year):
            if str(event.get("start", "")) != effort_date:
                continue
            event_hours = self._hours(str(event.get("consumed", "")))
            if event_hours != target_hours:
                continue
            try:
                effort_id = int(event["id"])
            except (KeyError, TypeError, ValueError):
                continue
            detail = self.effort_detail(effort_id)
            detail_hours = self._hours(detail["consumed"])
            if detail_hours is None:
                continue
            if (
                detail["date"] == effort_date
                and detail_hours == target_hours
                and detail["work"].strip() == work.strip()
            ):
                return detail
        return None

    def _ensure_no_duplicate(self, effort_date: str, consumed: float, work: str) -> None:
        duplicate = self._find_duplicate(effort_date, consumed, work)
        if duplicate is not None:
            raise SafetyError(f"Duplicate effort detected: effort ID {duplicate['id']}.")

    @staticmethod
    def _response_failed(source: str) -> bool:
        try:
            result = json.loads(source)
        except json.JSONDecodeError:
            return bool(re.search(r"\b(fail|failed|error)\b", source, flags=re.IGNORECASE))
        return result.get("status") in {"fail", "failed", "error"} or result.get("result") == "fail"

    def create_effort(
        self,
        object_type: str,
        object_id: int,
        date: str,
        consumed: float,
        work: str,
        left: float | None = None,
        apply: bool = False,
    ) -> dict[str, Any]:
        if not apply:
            raise SafetyError("Refusing to create effort without --apply.")
        self._validate_effort(object_type, object_id, date, consumed, work)
        if left is None:
            left = 999.0 if object_type == "task" else 0.0
        endpoint = f"effort-createForObject-{object_type}-{object_id}.html?onlybody=yes"
        form = self._authenticated_request("GET", endpoint).body
        required = ("dates[1]", "consumed[1]", "work[1]", "objectType[1]", "objectID[1]")
        if any(name not in form for name in required):
            raise ProtocolError("Chandao effort create form no longer matches the verified contract.")
        self._ensure_no_duplicate(date, consumed, work)
        data = {
            "id[1]": "1",
            "dates[1]": date,
            "consumed[1]": str(consumed),
            "left[1]": str(left),
            "work[1]": work,
            "objectType[1]": object_type,
            "objectID[1]": str(object_id),
        }
        result = self._authenticated_request("POST", endpoint, data=data)
        if self._response_failed(result.body):
            raise ChandaoError("Chandao rejected the effort create request.")
        verified = self._find_duplicate(date, consumed, work)
        if verified is None:
            raise ProtocolError("Created effort could not be verified by re-reading it.")
        return {
            "created": True,
            "id": verified["id"],
            "date": date,
            "consumed": consumed,
            "work": work,
        }

    def edit_effort(
        self,
        effort_id: int,
        date: str,
        consumed: float,
        work: str,
        left: float,
        object_id: int,
        apply: bool = False,
    ) -> dict[str, Any]:
        if not apply:
            raise SafetyError("Refusing to edit effort without --apply.")
        self._validate_effort("task", object_id, date, consumed, work)
        endpoint = f"effort-edit-{effort_id}.html?onlybody=yes"
        form = self._authenticated_request("GET", endpoint).body
        required = ("name='date'", "name='consumed'", "name='left'", "name='objectID'", "name='work'")
        if any(name not in form for name in required):
            raise ProtocolError("Chandao effort edit form no longer matches the verified contract.")
        data = {
            "date": date,
            "consumed": str(consumed),
            "left": str(left),
            "objectID": str(object_id),
            "work": work,
        }
        result = self._authenticated_request("POST", endpoint, data=data)
        if self._response_failed(result.body):
            raise ChandaoError("Chandao rejected the effort edit request.")
        detail = self.effort_detail(effort_id)
        if detail["date"] != date or detail["work"].strip() != work.strip():
            raise ProtocolError("Edited effort could not be verified by re-reading it.")
        return {"updated": True, "id": effort_id}

    def delete_effort(self, effort_id: int, apply: bool = False) -> dict[str, Any]:
        if not apply:
            raise SafetyError("Refusing to delete effort without --apply.")
        if effort_id <= 0:
            raise SafetyError("Effort ID must be positive.")
        existing = self.effort_detail(effort_id)
        try:
            effort_year = date.fromisoformat(existing["date"]).year
        except ValueError as error:
            raise ProtocolError("Existing effort did not expose an ISO date for delete verification.") from error
        endpoint = f"effort-delete-{effort_id}.html?onlybody=yes"
        result = self._authenticated_request("POST", endpoint)
        if self._response_failed(result.body):
            raise ChandaoError("Chandao rejected the effort delete request.")
        remaining = self.calendar_efforts(effort_year)
        if any(item.get("id") == effort_id for item in remaining):
            raise ProtocolError("Deleted effort still appears in the re-read effort list.")
        return {"deleted": True, "id": effort_id, "verified": True}


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browserless Chandao API client")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--base-url", default=os.environ.get("CHANDAO_BASE_URL", DEFAULT_BASE_URL))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("auth-check")
    for name in ("my-bugs", "my-tasks"):
        query = subparsers.add_parser(name)
        query.add_argument("--scope", default="assignedTo")
        query.add_argument("--limit", type=int, default=20)
        query.add_argument("--page", type=int, default=1)
    bug = subparsers.add_parser("bug")
    bug.add_argument("--id", type=int, required=True)
    resolve_bug = subparsers.add_parser("resolve-bug")
    resolve_bug.add_argument("--id", type=int, required=True)
    resolve_bug.add_argument("--resolution", default="fixed")
    resolve_bug.add_argument("--resolved-build", default="trunk")
    resolve_bug.add_argument("--comment")
    resolve_bug.add_argument("--apply", action="store_true")
    task = subparsers.add_parser("task")
    task.add_argument("--id", type=int, required=True)
    my_efforts = subparsers.add_parser("my-efforts")
    my_efforts.add_argument("--scope", choices=("all", "thisweek", "lastweek", "thismonth", "lastmonth"), default="all")
    calendar = subparsers.add_parser("calendar-efforts")
    calendar.add_argument("--year", type=int, required=True)
    effort = subparsers.add_parser("effort")
    effort.add_argument("--id", type=int, required=True)
    create = subparsers.add_parser("create-effort")
    create.add_argument("--object-type", choices=("task", "bug"), required=True)
    create.add_argument("--object-id", type=int, required=True)
    create.add_argument("--date", required=True)
    create.add_argument("--consumed", type=float, required=True)
    create.add_argument("--work", required=True)
    create.add_argument("--left", type=float)
    create.add_argument("--apply", action="store_true")
    edit = subparsers.add_parser("edit-effort")
    edit.add_argument("--id", type=int, required=True)
    edit.add_argument("--date", required=True)
    edit.add_argument("--consumed", type=float, required=True)
    edit.add_argument("--work", required=True)
    edit.add_argument("--left", type=float, required=True)
    edit.add_argument("--object-id", type=int, required=True)
    edit.add_argument("--apply", action="store_true")
    delete = subparsers.add_parser("delete-effort")
    delete.add_argument("--id", type=int, required=True)
    delete.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        client = ChandaoClient.from_environment(args.workspace, args.base_url)
        if args.command == "auth-check":
            result = client.auth_check()
        elif args.command == "my-bugs":
            result = client.my_bugs(args.scope, args.limit, args.page)
        elif args.command == "bug":
            result = client.bug_detail(args.id)
        elif args.command == "resolve-bug":
            result = client.resolve_bug(
                args.id, args.resolution, args.resolved_build, args.comment, args.apply
            )
        elif args.command == "task":
            result = client.task_detail(args.id)
        elif args.command == "my-tasks":
            result = client.my_tasks(args.scope, args.limit, args.page)
        elif args.command == "my-efforts":
            result = client.my_efforts(args.scope)
        elif args.command == "calendar-efforts":
            result = client.calendar_efforts(args.year)
        elif args.command == "effort":
            result = client.effort_detail(args.id)
        elif args.command == "create-effort":
            result = client.create_effort(
                args.object_type, args.object_id, args.date, args.consumed, args.work, args.left, args.apply
            )
        elif args.command == "edit-effort":
            result = client.edit_effort(
                args.id, args.date, args.consumed, args.work, args.left, args.object_id, args.apply
            )
        else:
            result = client.delete_effort(args.id, args.apply)
        _emit(result)
        return 0
    except ChandaoError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
