"""Offline regression tests; use synthetic credentials and no remote services."""
from __future__ import annotations

import base64
import contextlib
import dataclasses
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import releasego_config as config
import releasego_doctor as doctor
import releasego_git_compare as compare
import releasego_git_tag as tags
import releasego_gitlab_session as gitlab
import releasego_http_session as releasego
import releasego_jenkins_session as jenkins
import releasego_migrate as migrate


TEST_HOME = Path.home()
CLEAN_ENV = {"USERPROFILE": str(TEST_HOME), "HOME": str(TEST_HOME)}

class Reply:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, url):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return b'{}'

    def geturl(self):
        return self.url


class Recorder:
    def __init__(self):
        self.requests = []

    def open(self, request, **kwargs):
        self.requests.append(request)
        return Reply(request.full_url)


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.dict(os.environ, CLEAN_ENV, clear=True):
            self.cfg = dataclasses.replace(
                config.load_config(Path(self.temp.name)),
                username="fixture-account-73", password="fixture-secret-73!",
                gitlab_base_url="https://git.example.test",
                jenkins_base_url="https://ci.example.test",
                releasego_base_url="https://release.example.test",
            )

    def test_jenkins_rejects_foreign_origin_before_open(self):
        recorder = Recorder()
        with patch.object(jenkins.urllib.request, "build_opener", return_value=recorder):
            for url in ["https://other.example.test/job/a", "http://ci.example.test/job/a",
                        "https://ci.example.test:444/job/a", "https://ci.example.test:0/job/a", "https://user:pass@ci.example.test/job/a"]:
                with self.subTest(url=url), self.assertRaises(SystemExit):
                    jenkins.JenkinsHttpSession(self.cfg).job_status(url)
        self.assertEqual(recorder.requests, [])

    def test_jenkins_same_origin_default_port_works(self):
        recorder = Recorder()
        with patch.object(jenkins.urllib.request, "build_opener", return_value=recorder):
            jenkins.JenkinsHttpSession(self.cfg).job_status("https://CI.EXAMPLE.TEST:443/job/a")
        self.assertEqual(len(recorder.requests), 1)
        self.assertTrue(recorder.requests[0].get_header("Authorization").startswith("Basic "))

    def test_http_configs_are_rejected_before_login(self):
        for cls, field in [(gitlab.GitLabHttpSession, "gitlab_base_url"),
                           (releasego.ReleaseGoHttpSession, "releasego_base_url"),
                           (jenkins.JenkinsHttpSession, "jenkins_base_url")]:
            with self.subTest(field=field), self.assertRaises(SystemExit):
                cls(dataclasses.replace(self.cfg, **{field: "http://unsafe.example.test"}))

    def test_gitlab_safe_default(self):
        with patch.dict(os.environ, CLEAN_ENV, clear=True):
            self.assertTrue(config.load_config(Path(self.temp.name)).gitlab_base_url.startswith("https://"))

    def test_session_requests_reject_foreign_urls(self):
        for cls in [gitlab.GitLabHttpSession, releasego.ReleaseGoHttpSession]:
            session = cls(self.cfg)
            session.opener = Recorder()
            with self.subTest(client=cls.__name__), self.assertRaises(SystemExit):
                session._request("GET", "https://other.example.test/data")
            self.assertEqual(session.opener.requests, [])

    def test_redirects_never_cross_origin_or_downgrade(self):
        for cls, base in [(gitlab.GitLabHttpSession, self.cfg.gitlab_base_url),
                          (releasego.ReleaseGoHttpSession, self.cfg.releasego_base_url)]:
            session = cls(self.cfg)
            handler = next(h for h in session.opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
            req = urllib.request.Request(base + "/login")
            for url in ["https://other.example.test/login", base.replace("https:", "http:") + "/login"]:
                with self.subTest(client=cls.__name__, url=url), self.assertRaises(SystemExit):
                    handler.redirect_request(req, None, 302, "Found", {}, url)
            redirected = handler.redirect_request(req, None, 302, "Found", {}, base + "/home")
            self.assertEqual(redirected.full_url, base + "/home")

    def test_structured_and_log_redaction(self):
        payload = {"username": "account-to-hide", "parameters": [{"name": "DB_PASSWORD", "value": "unknown-secret"}],
                   "textHead": "password=log-secret Authorization: Bearer auth-secret", "access_token": "api-secret"}
        for module in [gitlab, releasego, jenkins]:
            with self.subTest(module=module.__name__):
                output = module.safe_json(payload)
                for secret in ["account-to-hide", "unknown-secret", "log-secret", "auth-secret", "api-secret"]:
                    self.assertNotIn(secret, output)

    def test_account_aliases_and_parameter_json_inside_logs(self):
        payload = {"parameters": [{"name": "DB_USERNAME", "value": "other-account"}],
                   "hasPassword": "presence-secret", "hasUsername": True,
                   "log": 'user=log-account login=login-account INFO {"value":"nested-secret","name":"DB_PASSWORD"}'}
        result = json.loads(jenkins.safe_json(payload))
        output = json.dumps(result)
        for value in ["other-account", "presence-secret", "log-account", "login-account", "nested-secret"]:
            self.assertNotIn(value, output)
        self.assertIs(result["hasUsername"], True)

    def test_doctor_redacts_entire_report(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["doctor", "--json"]), patch.object(doctor, "load_config", return_value=self.cfg), \
             patch.object(doctor, "check_cdp", return_value={"error": self.cfg.password}), \
             patch.object(doctor, "chrome_candidates", return_value=["/Users/" + self.cfg.username + "/Chrome"]), \
             patch.object(doctor, "run_version", return_value={}), contextlib.redirect_stdout(output):
            doctor.main()
        self.assertNotIn(self.cfg.password, output.getvalue())
        self.assertNotIn(self.cfg.username, output.getvalue())

    def test_cli_redacts_config_secrets_before_log_truncation(self):
        text = "x" * 10 + self.cfg.password + " " + self.cfg.username
        response = jenkins.HttpResponse(200, self.cfg.jenkins_base_url, "text/plain", {}, None, text)
        output = io.StringIO()
        argv = ["jenkins", "progressive-log", "--build-url", self.cfg.jenkins_base_url + "/job/a/1", "--max-chars", "22"]
        with patch.object(sys, "argv", argv), patch.object(jenkins, "load_config", return_value=self.cfg), \
             patch.object(jenkins.JenkinsHttpSession, "progressive_log", return_value=response), contextlib.redirect_stdout(output):
            jenkins.main()
        self.assertNotIn(self.cfg.password[:12], output.getvalue())

    def test_cli_redacts_encoded_credentials(self):
        token = base64.b64encode((self.cfg.username + ":" + self.cfg.password).encode()).decode()
        response = jenkins.HttpResponse(200, self.cfg.jenkins_base_url, "text/plain", {}, None, "opaque " + token)
        output = io.StringIO()
        with patch.object(sys, "argv", ["jenkins", "progressive-log", "--build-url", self.cfg.jenkins_base_url]), \
             patch.object(jenkins, "load_config", return_value=self.cfg), \
             patch.object(jenkins.JenkinsHttpSession, "progressive_log", return_value=response), contextlib.redirect_stdout(output):
            jenkins.main()
        self.assertNotIn(token, output.getvalue())

    def test_other_cli_outputs_redact_config_credentials(self):
        payload = {"message": self.cfg.password, "username": self.cfg.username}
        for module, client, method, argv, response in [
            (releasego, releasego.ReleaseGoHttpSession, "release_list", ["http", "release-list"],
             releasego.JsonResponse(200, self.cfg.releasego_base_url, "application/json", payload, "")),
            (gitlab, gitlab.GitLabHttpSession, "compare", ["gitlab", "compare", "--project", "a/b", "--from-ref", "a", "--to-ref", "b", "--full"],
             gitlab.HttpResponse(200, self.cfg.gitlab_base_url, "application/json", payload, "")),
        ]:
            output = io.StringIO()
            with self.subTest(client=client.__name__), patch.object(sys, "argv", argv), \
                 patch.object(module, "load_config", return_value=self.cfg), patch.object(client, "login"), \
                 patch.object(client, method, return_value=response), contextlib.redirect_stdout(output):
                module.main()
            self.assertNotIn(self.cfg.password, output.getvalue())
            self.assertNotIn(self.cfg.username, output.getvalue())

    def test_non_json_errors_redact_before_truncation(self):
        body = "x" * 190 + self.cfg.password
        session = gitlab.GitLabHttpSession(self.cfg)
        response = gitlab.HttpResponse(200, self.cfg.gitlab_base_url, "text/html", None, body)
        with patch.object(session, "_request", return_value=response), self.assertRaises(SystemExit) as error:
            session.api_json("/api/v4/projects")
        self.assertNotIn(self.cfg.password[:8], str(error.exception))

    def test_jenkins_redirect_handler_validates_even_when_following(self):
        for follow in [False, True]:
            handlers = []
            def builder(*args):
                handlers.extend(args)
                return Recorder()
            session = jenkins.JenkinsHttpSession(self.cfg)
            with patch.object(urllib.request, "build_opener", side_effect=builder):
                session.request("GET", "/job/a", follow_redirects=follow)
            handler = next(h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
            with self.subTest(follow=follow), self.assertRaises(SystemExit):
                handler.redirect_request(urllib.request.Request(self.cfg.jenkins_base_url), None, 302, "Found", {}, "https://other.example.test/")


class PortabilityTests(unittest.TestCase):
    def test_windows_and_mac_user_chrome_locations(self):
        for platform_name, fragment in [("Windows", "AppData/Local/Google/Chrome/Application/chrome.exe"),
                                        ("Darwin", "Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]:
            with self.subTest(platform=platform_name), patch.object(doctor.platform, "system", return_value=platform_name), \
                 patch.object(doctor.shutil, "which", return_value=None), patch.dict(os.environ, CLEAN_ENV, clear=True):
                candidates = [Path(p).as_posix() for p in doctor.chrome_candidates(None)]
                expected = (Path.home() / fragment).as_posix()
                self.assertIn(expected, candidates)

    def test_git_helpers_use_utf8_independent_of_locale(self):
        result = subprocess.CompletedProcess([], 0, "中文", "")
        for module in [compare, migrate]:
            with self.subTest(module=module.__name__), patch.object(module.subprocess, "run", return_value=result) as runner:
                module.run(["git", "status"])
                self.assertEqual(runner.call_args.kwargs.get("encoding"), "utf-8")

    def test_tag_default_work_dir_uses_environment(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, dict(CLEAN_ENV, RELEASEGO_WORK_DIR=temp), clear=True), \
             patch.object(config, "read_local_config", return_value={}):
            args = tags.build_parser().parse_args(["--repo-url", "repo", "--tag-name", "example"])
            self.assertEqual(args.work_dir, Path(temp) / "git-tag-work")

    def test_config_expands_home_paths(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, CLEAN_ENV, clear=True):
            (Path(temp) / "config.local.json").write_text(json.dumps({"workDir": "~/release-test", "chromePath": "~/Chrome"}), encoding="utf-8-sig")
            cfg = config.load_config(Path(temp))
            self.assertEqual(Path(cfg.work_dir), Path.home() / "release-test")
            self.assertEqual(Path(cfg.chrome_path), Path.home() / "Chrome")


class GitIntegrationTests(unittest.TestCase):
    def test_compare_and_migrate_preserve_patch_bytes_and_configured_cache(self):
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        with tempfile.TemporaryDirectory(prefix="releasego-test-") as temp:
            root = Path(temp)
            isolated_scripts = root / "isolated-skill" / "scripts"
            isolated_scripts.mkdir(parents=True)
            for path in scripts.glob("*.py"):
                shutil.copy2(path, isolated_scripts / path.name)
            scripts = isolated_scripts
            source = root / "中文 source"
            source.mkdir()

            def git(*args, cwd=source):
                return subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True).stdout

            git("init", "-b", "release")
            git("config", "user.name", "Audit Fixture")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "core.autocrlf", "false")
            (source / "text.txt").write_bytes("原文\r\n".encode())
            (source / "raw.txt").write_bytes(b"old \x81\r\n")
            git("add", ".")
            git("commit", "-m", "fixture base")
            base = git("rev-parse", "HEAD").decode().strip()
            (source / "text.txt").write_bytes("新内容\r\n".encode())
            (source / "raw.txt").write_bytes(b"new \x81\r\n")
            git("add", ".")
            git("commit", "-m", "fixture change")
            head = git("rev-parse", "HEAD").decode().strip()
            expected_patch = git("diff", "--binary", base, head)
            out = root / "报告 output"
            work = root / "缓存 cache"
            env = dict(os.environ, RELEASEGO_WORK_DIR=str(work), RELEASEGO_GITLAB_BASE_URL="https://git.example.test", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", TINGYUN_USERNAME="fixture-user", TINGYUN_PASSWORD="fixture-password")
            subprocess.run([sys.executable, "-B", str(scripts / "releasego_git_compare.py"), "--repo-url", str(source),
                            "--base", base, "--head", head, "--out", str(out)], env=env, capture_output=True, check=True)
            self.assertEqual((out / "diff.patch").read_bytes(), expected_patch)
            self.assertTrue((work / "git-cache").is_dir())
            target = root / "目标 target"
            git("clone", "-q", str(source), str(target))
            git("checkout", "-B", "release", base, cwd=target)
            git("config", "core.autocrlf", "false", cwd=target)
            subprocess.run([sys.executable, "-B", str(scripts / "releasego_migrate.py"), "--target-repo", str(target),
                            "--target-branch", "release", "--patch", str(out / "diff.patch")], env=env, capture_output=True, check=True)
            self.assertEqual((target / "text.txt").read_bytes(), (source / "text.txt").read_bytes())
            self.assertEqual((target / "raw.txt").read_bytes(), (source / "raw.txt").read_bytes())
            self.assertEqual(git("rev-parse", "HEAD", cwd=target).decode().strip(), base)


if __name__ == "__main__":
    unittest.main()
