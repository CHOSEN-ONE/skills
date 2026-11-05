"""Explicit GitLab-only HTTP exception; no real credentials or network."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import releasego_config as config
import releasego_gitlab_session as gitlab
import releasego_http_session as releasego
import releasego_jenkins_session as jenkins


class GitLabHttpPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with patch.dict(os.environ, {}, clear=True):
            cfg = config.load_config(self.root)
        values = vars(cfg) | {"gitlab_base_url": "http://git.example.test", "gitlab_allow_http": True,
                             "username": "fixture-user", "password": "fixture-password"}
        self.cfg = types.SimpleNamespace(**values)

    def session(self):
        try:
            return gitlab.GitLabHttpSession(self.cfg)
        except SystemExit:
            self.fail("An explicitly enabled GitLab HTTP origin must be accepted")

    def test_local_opt_in_and_false_override(self):
        for value in [True, False]:
            (self.root / "config.local.json").write_text(json.dumps({"gitlabAllowHttp": value}), encoding="utf-8")
            with self.subTest(value=value), patch.dict(os.environ, {"RELEASEGO_GITLAB_ALLOW_HTTP": "true"}, clear=True):
                self.assertIs(getattr(config.load_config(self.root), "gitlab_allow_http", None), value)

    def test_env_opt_in_is_strict_and_defaults_off(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIs(getattr(config.load_config(self.root), "gitlab_allow_http", None), False)
        for value, expected in [("true", True), ("1", True), ("false", False), ("0", False)]:
            with self.subTest(value=value), patch.dict(os.environ, {"RELEASEGO_GITLAB_ALLOW_HTTP": value}, clear=True):
                self.assertIs(getattr(config.load_config(self.root), "gitlab_allow_http", None), expected)
        for value in ["yesplease", "anything"]:
            with self.subTest(value=value), patch.dict(os.environ, {"RELEASEGO_GITLAB_ALLOW_HTTP": value}, clear=True), self.assertRaises(SystemExit):
                config.load_config(self.root)

    def test_local_string_false_is_not_truthy(self):
        (self.root / "config.local.json").write_text('{"gitlabAllowHttp":"false"}', encoding="utf-8")
        with self.assertRaises(SystemExit):
            config.load_config(self.root)

    def test_opted_http_allows_only_same_origin_and_default_port(self):
        session = self.session()
        with patch.object(session.opener, "open", side_effect=RuntimeError("transport intercepted")) as opened:
            with self.assertRaisesRegex(RuntimeError, "transport intercepted"):
                session._request("POST", "http://GIT.EXAMPLE.TEST:80/users/auth/ldapmain/callback", form_body={"password": self.cfg.password})
            self.assertEqual(opened.call_count, 1)
            for url in ["http://other.example.test/", "http://git.example.test:8080/", "http://git.example.test:0/",
                        "http://user:password@git.example.test/", "https://git.example.test/"]:
                with self.subTest(url=url), self.assertRaises(SystemExit):
                    session._request("GET", url)
            self.assertEqual(opened.call_count, 1)

    def test_opted_http_redirects_cannot_escape_origin(self):
        session = self.session()
        handler = next(h for h in session.opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
        request = urllib.request.Request(self.cfg.gitlab_base_url + "/login")
        self.assertEqual(handler.redirect_request(request, None, 302, "Found", {}, self.cfg.gitlab_base_url + "/home").full_url,
                         self.cfg.gitlab_base_url + "/home")
        for url in ["http://other.example.test/", "http://git.example.test:8080/", "https://git.example.test/"]:
            with self.subTest(url=url), self.assertRaises(SystemExit):
                handler.redirect_request(request, None, 302, "Found", {}, url)

    def test_https_configuration_never_downgrades_even_with_opt_in(self):
        self.cfg.gitlab_base_url = "https://git.example.test"
        session = gitlab.GitLabHttpSession(self.cfg)
        with patch.object(session.opener, "open") as opened, self.assertRaises(SystemExit):
            session._request("GET", "http://git.example.test/")
        opened.assert_not_called()

    def test_disabled_http_and_other_services_remain_strict(self):
        self.cfg.gitlab_allow_http = False
        with self.assertRaises(SystemExit):
            gitlab.GitLabHttpSession(self.cfg)
        self.cfg.gitlab_allow_http = True
        self.cfg.releasego_base_url = "http://release.example.test"
        self.cfg.jenkins_base_url = "http://ci.example.test"
        for cls in [releasego.ReleaseGoHttpSession, jenkins.JenkinsHttpSession]:
            with self.subTest(client=cls.__name__), self.assertRaises(SystemExit):
                cls(self.cfg)


if __name__ == "__main__":
    unittest.main()
