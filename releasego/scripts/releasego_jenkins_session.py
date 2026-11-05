#!/usr/bin/env python3
"""Browserless Jenkins API helpers using LDAP basic auth."""

from __future__ import annotations

import argparse
import base64
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


DEFAULT_TIMEOUT = 25


@dataclass
class HttpResponse:
    status: int
    url: str
    content_type: str
    headers: dict[str, str]
    data: Any | None
    text: str


class JenkinsHttpSession:
    def __init__(self, config: ReleaseGoConfig, timeout: int = DEFAULT_TIMEOUT):
        self.config = config
        self.base_url = config.jenkins_base_url.rstrip("/")
        self.timeout = timeout
        https_origin(self.base_url)
        self.redactor = Redactor((config.username, config.password))

    def _auth_header(self) -> str:
        if not self.config.username or not self.config.password:
            raise SystemExit("Missing Tingyun credentials. Configure config.local.json or environment variables.")
        token = base64.b64encode(f"{self.config.username}:{self.config.password}".encode("utf-8")).decode("ascii")
        return "Basic " + token

    @staticmethod
    def _url(path_or_url: str, params: dict[str, Any] | None = None) -> str:
        url = path_or_url
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return url

    def request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        form_body: dict[str, Any] | None = None,
        follow_redirects: bool = False,
    ) -> HttpResponse:
        url = path_or_url if path_or_url.startswith(("http://", "https://")) else self.base_url + "/" + path_or_url.lstrip("/")
        require_same_origin(url, self.base_url)
        data = None
        headers = {
            "Authorization": self._auth_header(),
            "User-Agent": "Mozilla/5.0 ReleaseGoShare/1.0",
            "Accept": "application/json, text/plain, */*",
        }
        if form_body is not None:
            data = urllib.parse.urlencode(form_body).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        opener = urllib.request.build_opener(SameOriginRedirectHandler(self.base_url, follow=follow_redirects))
        req = urllib.request.Request(self._url(url, params), data=data, headers=headers, method=method.upper())
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
                status = resp.status
                final_url = resp.geturl()
                response_headers = dict(resp.headers.items())
                content_type = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
            final_url = exc.geturl()
            response_headers = dict(exc.headers.items())
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
        return HttpResponse(status=status, url=final_url, content_type=content_type, headers=response_headers, data=parsed, text=text)

    def whoami(self) -> HttpResponse:
        return self.request("GET", "/whoAmI/api/json")

    def job_status(self, job_url: str) -> HttpResponse:
        return self.request(
            "GET",
            job_url.rstrip("/") + "/api/json",
            params={"tree": "nextBuildNumber,lastBuild[number,result,building,url,timestamp,duration],builds[number,result,building,url,timestamp,duration]{0,8}"},
        )

    def job_parameters(self, job_url: str) -> HttpResponse:
        return self.request(
            "GET",
            job_url.rstrip("/") + "/api/json",
            params={"tree": "nextBuildNumber,property[parameterDefinitions[name,type,description,defaultParameterValue[value]]],actions[parameterDefinitions[name,type,description,defaultParameterValue[value]]]"},
        )

    def build_status(self, build_url: str) -> HttpResponse:
        return self.request(
            "GET",
            build_url.rstrip("/") + "/api/json",
            params={"tree": "number,url,building,result,duration,estimatedDuration,timestamp,actions[parameters[name,value]],executor[currentExecutable[number,url]]"},
        )

    def progressive_log(self, build_url: str, start: int = 0) -> HttpResponse:
        return self.request("GET", build_url.rstrip("/") + "/logText/progressiveText", params={"start": start})

    def crumb(self) -> HttpResponse:
        return self.request("GET", "/crumbIssuer/api/json")

    def trigger_build(self, job_url: str, parameters: dict[str, Any]) -> HttpResponse:
        return self.request("POST", job_url.rstrip("/") + "/buildWithParameters", form_body=parameters)

    def queue(self) -> HttpResponse:
        return self.request("GET", "/queue/api/json")

    def queue_item(self, queue_id: int) -> HttpResponse:
        return self.request("GET", f"/queue/item/{queue_id}/api/json")

    def computer(self) -> HttpResponse:
        return self.request("GET", "/computer/api/json")






def parameter_definitions(data: Any) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return definitions
    seen: set[tuple[Any, Any]] = set()
    for holder in (data.get("property") or []) + (data.get("actions") or []):
        if not isinstance(holder, dict):
            continue
        for item in holder.get("parameterDefinitions") or []:
            if not isinstance(item, dict):
                continue
            key = (item.get("name"), item.get("type"))
            if key in seen:
                continue
            seen.add(key)
            definitions.append(
                {
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "hasDefault": bool((item.get("defaultParameterValue") or {}).get("value")),
                }
            )
    return definitions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Use Jenkins APIs without browser automation.")
    parser.add_argument("--skill-root", type=Path)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth-test", help="Verify LDAP basic auth through /whoAmI/api/json.")

    job = sub.add_parser("job-status")
    job.add_argument("--job-url", required=True)

    params = sub.add_parser("job-parameters")
    params.add_argument("--job-url", required=True)

    build = sub.add_parser("build-status")
    build.add_argument("--build-url", required=True)

    log = sub.add_parser("progressive-log")
    log.add_argument("--build-url", required=True)
    log.add_argument("--start", type=int, default=0)
    log.add_argument("--max-chars", type=int, default=500)

    sub.add_parser("crumb-test", help="Probe /crumbIssuer/api/json. 404 is expected on this Jenkins instance.")

    sub.add_parser("queue", help="Read Jenkins queue.")

    queue_item = sub.add_parser("queue-item", help="Read one Jenkins queue item.")
    queue_item.add_argument("--queue-id", type=int, required=True)

    sub.add_parser("computer", help="Read Jenkins executor/computer summary.")

    trigger = sub.add_parser("trigger-build", help="Submit a Jenkins parameterized build. This has side effects.")
    trigger.add_argument("--job-url", required=True)
    trigger.add_argument("--tag", required=True)
    trigger.add_argument("--tag-parameter", default="TAG")
    trigger.add_argument("--sonar-skip", choices=["true", "false"], default=None)
    trigger.add_argument("--confirm-trigger", choices=["yes"], required=True, help="Required because this queues a real build.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cfg = load_config(args.skill_root, require_credentials=True)
    session = JenkinsHttpSession(cfg, timeout=args.timeout)
    safe_json = session.redactor.json

    if args.command == "auth-test":
        response = session.whoami()
        data = response.data if isinstance(response.data, dict) else {}
        print(safe_json({"httpStatus": response.status, "authenticated": data.get("authenticated"), "anonymous": data.get("anonymous"), "namePresent": bool(data.get("name")), "credentialSource": cfg.credential_source}))
        return 0

    if args.command == "job-status":
        response = session.job_status(args.job_url)
        data = response.data if isinstance(response.data, dict) else {}
        print(safe_json({"httpStatus": response.status, "nextBuildNumber": data.get("nextBuildNumber"), "lastBuild": data.get("lastBuild"), "buildCount": len(data.get("builds", [])) if isinstance(data.get("builds"), list) else None}))
        return 0

    if args.command == "job-parameters":
        response = session.job_parameters(args.job_url)
        data = response.data if isinstance(response.data, dict) else {}
        print(safe_json({"httpStatus": response.status, "nextBuildNumber": data.get("nextBuildNumber"), "parameterDefinitions": parameter_definitions(data)}))
        return 0

    if args.command == "build-status":
        response = session.build_status(args.build_url)
        data = response.data if isinstance(response.data, dict) else {}
        parameters = []
        for action in data.get("actions") or []:
            if isinstance(action, dict):
                parameters.extend(action.get("parameters") or [])
        print(safe_json({"httpStatus": response.status, "number": data.get("number"), "url": data.get("url"), "building": data.get("building"), "result": data.get("result"), "parameters": parameters}))
        return 0

    if args.command == "progressive-log":
        response = session.progressive_log(args.build_url, args.start)
        print(safe_json({"httpStatus": response.status, "xMoreData": response.headers.get("X-More-Data"), "xTextSize": response.headers.get("X-Text-Size"), "textHead": session.redactor.text(response.text)[: args.max_chars]}))
        return 0

    if args.command == "crumb-test":
        response = session.crumb()
        print(safe_json({"httpStatus": response.status, "contentType": response.content_type, "jsonKeys": sorted(response.data.keys()) if isinstance(response.data, dict) else None}))
        return 0

    if args.command == "queue":
        response = session.queue()
        data = response.data if isinstance(response.data, dict) else {}
        items = data.get("items", []) if isinstance(data.get("items"), list) else []
        print(safe_json({"httpStatus": response.status, "itemsCount": len(items), "items": [{"id": item.get("id"), "taskName": (item.get("task") or {}).get("name") if isinstance(item.get("task"), dict) else None, "why": item.get("why"), "blocked": item.get("blocked"), "stuck": item.get("stuck")} for item in items]}))
        return 0

    if args.command == "queue-item":
        response = session.queue_item(args.queue_id)
        data = response.data if isinstance(response.data, dict) else {}
        executable = data.get("executable") if isinstance(data.get("executable"), dict) else {}
        print(safe_json({"httpStatus": response.status, "id": data.get("id"), "why": data.get("why"), "blocked": data.get("blocked"), "stuck": data.get("stuck"), "executable": {"number": executable.get("number"), "url": executable.get("url")}}))
        return 0

    if args.command == "computer":
        response = session.computer()
        data = response.data if isinstance(response.data, dict) else {}
        computers = data.get("computer", []) if isinstance(data.get("computer"), list) else []
        print(safe_json({"httpStatus": response.status, "busyExecutors": data.get("busyExecutors"), "totalExecutors": data.get("totalExecutors"), "computerCount": len(computers)}))
        return 0

    if args.command == "trigger-build":
        form: dict[str, Any] = {args.tag_parameter: args.tag}
        if args.sonar_skip is not None:
            form["sonar.skip"] = args.sonar_skip
        response = session.trigger_build(args.job_url, form)
        print(safe_json({"httpStatus": response.status, "location": response.headers.get("Location"), "url": response.url, "contentType": response.content_type}))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
