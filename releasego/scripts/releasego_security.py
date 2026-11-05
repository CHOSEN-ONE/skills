"""Shared authentication boundaries and output-only credential redaction."""
from __future__ import annotations

import base64
import html
import json
import re
import urllib.parse
import urllib.request
from typing import Any, Iterable


def validated_origin(url: str, *, allow_http: bool = False) -> tuple[str, str, int]:
    try:
        if any(ord(char) <= 32 or ord(char) == 127 for char in url) or "\\" in url:
            raise ValueError
        parts = urllib.parse.urlsplit(url)
        allowed_schemes = {"https", "http"} if allow_http else {"https"}
        if parts.scheme not in allowed_schemes or not parts.hostname or parts.username is not None or parts.password is not None or parts.fragment:
            raise ValueError
        port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
        if port == 0:
            raise ValueError
        return parts.scheme, parts.hostname.encode("idna").decode("ascii").lower(), port
    except (ValueError, UnicodeError):
        raise SystemExit("Authentication URL rejected: require HTTPS, or explicitly enabled GitLab HTTP, without embedded credentials or invalid ports. No automatic scheme fallback.") from None


def https_origin(url: str) -> tuple[str, str, int]:
    return validated_origin(url)


def require_same_origin(url: str, base_url: str, *, allow_http: bool = False) -> str:
    if validated_origin(url, allow_http=allow_http) != validated_origin(base_url, allow_http=allow_http):
        raise SystemExit("Blocked authentication request or redirect outside the configured origin.")
    return url


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, base_url: str, follow: bool = True, *, allow_http: bool = False):
        self.base_url = base_url
        self.follow = follow
        self.allow_http = allow_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require_same_origin(newurl, self.base_url, allow_http=self.allow_http)
        if not self.follow:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return bool(re.fullmatch(r".*(?:password|passwd|secret|token|apikey|username|user|login)|pwd|authorization|proxyauthorization|cookie|setcookie", normalized))


class Redactor:
    def __init__(self, credentials: Iterable[str | None] = ()):
        values = tuple(value for value in credentials if value)
        variants: set[str] = set()
        for value in values:
            variants.update((value, urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value),
                             html.escape(value), json.dumps(value, ensure_ascii=True)[1:-1],
                             base64.b64encode(value.encode("utf-8")).decode("ascii")))
        if len(values) == 2:
            variants.add(base64.b64encode(":".join(values).encode("utf-8")).decode("ascii"))
        self.variants = tuple(sorted(variants, key=len, reverse=True))

    def text(self, value: str) -> str:
        # Jenkins may embed name/value parameter objects inside plain log text.
        def redact_parameter_object(match):
            candidate = match.group(0)
            if '"name"' not in candidate and '"key"' not in candidate:
                return candidate
            try:
                return json.dumps(self.scrub(json.loads(candidate)), ensure_ascii=False)
            except (ValueError, TypeError):
                return candidate

        value = re.sub(r"\{[^{}]*\}", redact_parameter_object, value)
        for secret in self.variants:
            value = value.replace(secret, "<redacted>")
        value = re.sub(r"(?i)\b((?:proxy-)?authorization\s*[:=]\s*)(?:(?:basic|bearer)\s+)?[^\s,;<>]+", r"\1<redacted>", value)
        value = re.sub(r"(?i)\b((?:set-)?cookie\s*[:=]\s*)[^\r\n]+", r"\1<redacted>", value)
        value = re.sub(r'''(?ix)(["']?(?:[\w.-]*(?:password|passwd|secret|token|api[_-]?key|username|user|login)|pwd)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s&,;<>]+)''', r"\1<redacted>", value)
        value = re.sub(r"(?i)(https?://)[^/\s@]+@", r"\1<redacted>@", value)
        return value

    def scrub(self, value: Any) -> Any:
        if isinstance(value, dict):
            parameter_secret = sensitive_key(value.get("name", value.get("key", "")))
            result = {}
            for key, item in value.items():
                name = str(key)
                presence_flag = isinstance(item, bool) and (name.lower().startswith("has") or name.lower().endswith("present"))
                sensitive = sensitive_key(name) or (parameter_secret and name.lower() in {"value", "defaultvalue", "defaultparametervalue"})
                result[self.text(name)] = "<redacted>" if sensitive and not presence_flag else self.scrub(item)
            return result
        if isinstance(value, (list, tuple)):
            return [self.scrub(item) for item in value]
        if isinstance(value, str):
            return self.text(value)
        return value

    def json(self, value: Any) -> str:
        return json.dumps(self.scrub(value), ensure_ascii=False, indent=2)


def safe_json(value: Any) -> str:
    return Redactor().json(value)
