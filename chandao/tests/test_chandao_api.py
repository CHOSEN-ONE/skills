import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from chandao_api import AuthenticationError, ChandaoClient, HttpResponse, ProtocolError, SafetyError, _parser  # noqa: E402


LOGIN_PAGE = """
<input type='hidden' name='verifyRand' id='verifyRand' value='123456' />
"""


BUG_LIST = """
<table><tr><td><a href='/pro/bug-view-1001.html?onlybody=yes' title='登录失败'>1001</a></td>
<td><a href='/pro/bug-view-1001.html?onlybody=yes' title='登录失败'>登录失败</a></td></tr></table>
"""


BUG_DETAIL = """
<title>BUG #1001 登录失败 - RUM-APP - 禅道</title>
<div class='detail-title'>重现步骤</div><div class='detail-content'>输入正确账号后仍然失败</div>
<th>Bug状态</th><td><span>激活</span></td>
<th>严重程度</th><td><span class='label-severity' data-severity='2'></span></td>
<th>优先级</th><td><span title='3'>3</span></td>
"""


TASK_LIST = """
<table><tr><td><a href='/pro/task-view-2001.html?onlybody=yes' title='修复登录'>2001</a></td>
<td><a href='/pro/task-view-2001.html?onlybody=yes' title='修复登录'>修复登录</a></td></tr></table>
"""


TASK_DETAIL = """
<title>TASK#2001 Fix login / RUM - ZenTao</title>
<th>\u6240\u5c5e\u9879\u76ee</th><td>RUM</td>
<th>\u6240\u5c5e\u6a21\u5757</th><td>Core</td>
<th>\u76f8\u5173\u9700\u6c42</th><td>Login support</td>
<th>\u6307\u6d3e\u7ed9</th><td>tester</td>
<th>\u4efb\u52a1\u7c7b\u578b</th><td>\u5f00\u53d1</td>
<th>\u4efb\u52a1\u72b6\u6001</th><td>\u8fdb\u884c\u4e2d</td>
<th>\u8fdb\u5ea6</th><td>50%</td>
<th>\u4f18\u5148\u7ea7</th><td>1</td>
<th>\u6700\u521d\u9884\u8ba1</th><td>8\u5de5\u65f6</td>
<th>\u603b\u8ba1\u6d88\u8017</th><td>4\u5de5\u65f6</td>
<th>\u9884\u8ba1\u5269\u4f59</th><td>4\u5de5\u65f6</td>
<th>\u9884\u8ba1\u5f00\u59cb</th><td>2026-07-17</td>
<th>\u5b9e\u9645\u5f00\u59cb</th><td>2026-07-17 09:00:00</td>
<th>\u622a\u6b62\u65e5\u671f</th><td>2026-07-18</td>
<div class='detail'><div class='detail-title'>\u4efb\u52a1\u63cf\u8ff0</div><div class='detail-content article-content'><p>Fix the login flow.</p></div></div>
<div class='detail'><div class='detail-title'>\u9700\u6c42\u63cf\u8ff0</div><div class='detail-content article-content'><p>Support login.</p></div></div>
<div class='detail'><div class='detail-title'>\u9a8c\u6536\u6807\u51c6</div><div class='detail-content article-content'><p>Login succeeds.</p></div></div>
"""


EFFORT_FORM = "dates[1] consumed[1] work[1] objectType[1] objectID[1]"
EFFORT_LIST = "<a href='/pro/effort-view-3001-my.html?onlybody=yes' title='修复登录'>修复登录</a>"
EFFORT_DETAIL = """
<th>日期</th><td>2026-07-14</td>
<th>耗时</th><td>4 小时</td>
<th>剩余</th><td>999</td>
<th>工作内容</th><td>修复登录</td>
<a href='/pro/task-view-2001.html'>任务</a>
"""


AUTH_HOME = "<title>我的地盘 - 禅道</title>"
LOGIN_REDIRECT = "<script>self.location='/pro/user-login-L3Byby9teS5odG1s.html';</script>"
PASSWORD_CHANGE_REDIRECT = "<script>self.location='/pro/my-changepassword.html?onlybody=yes';</script>"
UNAVAILABLE_BUG = "<script>alert('')</script><script>history.back(-1);</script>"
CALENDAR_PAGE = "config.ajaxGetEffortsUrl = '/pro/effort-ajaxGetEfforts-411-{year}.html?onlybody=yes';"
CALENDAR_EVENTS = json.dumps(
    [
        {
            "id": 3001,
            "title": "[T]修复登录",
            "start": "2026-07-14",
            "end": "2026-07-14",
            "url": "/pro/effort-view-3001.html?onlybody=yes",
            "consumed": "4",
        }
    ]
)

RESOLVE_FORM = """
<input type='text' name='resolvedDate' value='2026-07-29 10:00:00' />
<input type='hidden' name='status' value='resolved' />
<select name='resolution'>
  <option value='fixed'>\u5df2\u89e3\u51b3</option>
  <option value='notrepro'>\u65e0\u6cd5\u91cd\u73b0</option>
</select>
<select name='resolvedBuild'>
  <option value='trunk'>\u4e3b\u5e72</option>
</select>
<select name='assignedTo'>
  <option value='tester' selected>tester</option>
</select>
<textarea name='comment'></textarea>
"""

RESOLVED_BUG_DETAIL = """
<th>\u0042ug\u72b6\u6001</th><td>\u5df2\u89e3\u51b3</td>
<th>\u89e3\u51b3\u65b9\u6848</th><td>\u5df2\u89e3\u51b3</td>
<th>\u89e3\u51b3\u7248\u672c</th><td>\u4e3b\u5e72</td>
"""


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, data=None, headers=None):
        self.requests.append({"method": method, "url": url, "data": data or {}})
        if not self.responses:
            raise AssertionError(f"Unexpected request: {method} {url}")
        body = self.responses.pop(0)
        return HttpResponse(status=200, url=url, headers={}, body=body)


class ChandaoClientTest(unittest.TestCase):
    def make_client(self, transport):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        return ChandaoClient(
            workspace=Path(workspace.name),
            username="tester",
            password="secret",
            transport=transport,
        )

    def test_login_uses_double_md5_and_retries_original_read_once(self):
        transport = FakeTransport(
            [
                "<title>用户登录 - 禅道</title>",
                LOGIN_PAGE,
                json.dumps({"status": "success"}),
                AUTH_HOME,
                BUG_LIST,
            ]
        )
        client = self.make_client(transport)

        bugs = client.my_bugs()

        expected_hash = hashlib.md5(
            (hashlib.md5(b"secret").hexdigest() + "123456").encode("utf-8")
        ).hexdigest()
        self.assertEqual([{"id": 1001, "title": "登录失败"}], bugs)
        self.assertEqual("POST", transport.requests[2]["method"])
        self.assertEqual(expected_hash, transport.requests[2]["data"]["password"])
        self.assertEqual("0", transport.requests[2]["data"]["passwordStrength"])
        self.assertEqual(2, sum("my-bug-assignedTo" in item["url"] for item in transport.requests))

    def test_matches_chandao_password_strength_algorithm(self):
        self.assertEqual(0, ChandaoClient._password_strength("secret"))
        self.assertEqual(2, ChandaoClient._password_strength("Abcdefgh1!"))

    def test_parses_bug_detail_and_assigned_task_list(self):
        transport = FakeTransport([BUG_DETAIL, TASK_LIST])
        client = self.make_client(transport)

        detail = client.bug_detail(1001)
        tasks = client.my_tasks()

        self.assertEqual(1001, detail["id"])
        self.assertEqual("登录失败", detail["title"])
        self.assertEqual("RUM-APP", detail["product"])
        self.assertEqual("输入正确账号后仍然失败", detail["reproduction_steps"])
        self.assertEqual("激活", detail["status"])
        self.assertEqual("2", detail["severity"])
        self.assertEqual([{"id": 2001, "title": "修复登录"}], tasks)

    def test_parses_task_detail(self):
        transport = FakeTransport([TASK_DETAIL])
        client = self.make_client(transport)

        detail = client.task_detail(2001)

        self.assertEqual(
            {
                "id": 2001,
                "title": "Fix login",
                "project": "RUM",
                "module": "Core",
                "story": "Login support",
                "assignee": "tester",
                "type": "开发",
                "status": "进行中",
                "progress": "50%",
                "priority": "1",
                "estimate": "8工时",
                "consumed": "4工时",
                "left": "4工时",
                "est_started": "2026-07-17",
                "real_started": "2026-07-17 09:00:00",
                "deadline": "2026-07-18",
                "description": "Fix the login flow.",
                "story_description": "Support login.",
                "acceptance": "Login succeeds.",
            },
            detail,
        )
        self.assertIn("task-view-2001.html", transport.requests[0]["url"])

    def test_parser_exposes_task_detail_command(self):
        args = _parser().parse_args(["task", "--id", "2001"])

        self.assertEqual("task", args.command)
        self.assertEqual(2001, args.id)

    def test_rejects_a_bug_detail_page_that_only_returns_history_back(self):
        transport = FakeTransport([UNAVAILABLE_BUG])
        client = self.make_client(transport)

        with self.assertRaises(ProtocolError):
            client.bug_detail(1001)

    def test_reauthenticates_when_an_expired_session_returns_a_javascript_login_redirect(self):
        transport = FakeTransport(
            [LOGIN_REDIRECT, LOGIN_PAGE, json.dumps({"status": "success"}), AUTH_HOME, TASK_LIST]
        )
        client = self.make_client(transport)

        tasks = client.my_tasks()

        self.assertEqual([{"id": 2001, "title": "修复登录"}], tasks)
        self.assertEqual(2, sum("my-task-assignedTo" in item["url"] for item in transport.requests))

    def test_stops_when_chandao_requires_a_password_change(self):
        transport = FakeTransport([PASSWORD_CHANGE_REDIRECT])
        client = self.make_client(transport)

        with self.assertRaises(AuthenticationError):
            client.my_bugs()

        self.assertEqual(1, len(transport.requests))

    def test_rejects_write_without_apply_or_invalid_effort(self):
        transport = FakeTransport([])
        client = self.make_client(transport)

        with self.assertRaises(SafetyError):
            client.create_effort(
                object_type="task",
                object_id=2001,
                date="2026-07-14",
                consumed=4,
                work="修复登录",
                apply=False,
            )
        with self.assertRaises(SafetyError):
            client.create_effort(
                object_type="task",
                object_id=2001,
                date="2026-07-14",
                consumed=4.5,
                work="修复登录",
                apply=True,
            )
        self.assertEqual([], transport.requests)

    def test_create_verifies_the_new_effort_instead_of_treating_it_as_a_duplicate(self):
        transport = FakeTransport(
            [
                EFFORT_FORM,
                CALENDAR_PAGE,
                "[]",
                json.dumps({"status": "success"}),
                CALENDAR_PAGE,
                CALENDAR_EVENTS,
                EFFORT_DETAIL,
            ]
        )
        client = self.make_client(transport)

        result = client.create_effort(
            object_type="task",
            object_id=2001,
            date="2026-07-14",
            consumed=4,
            work="修复登录",
            apply=True,
        )

        self.assertEqual({"created": True, "id": 3001, "date": "2026-07-14", "consumed": 4, "work": "修复登录"}, result)
        self.assertEqual("POST", transport.requests[3]["method"])

    def test_lists_full_my_efforts_from_the_all_scope_and_parses_my_suffix(self):
        transport = FakeTransport([EFFORT_LIST])
        client = self.make_client(transport)

        efforts = client.my_efforts()

        self.assertEqual([{"id": 3001, "title": "修复登录"}], efforts)
        self.assertIn("my-effort-all", transport.requests[0]["url"])

    def test_reads_calendar_efforts_from_the_discovered_account_year_endpoint(self):
        transport = FakeTransport([CALENDAR_PAGE, CALENDAR_EVENTS])
        client = self.make_client(transport)

        events = client.calendar_efforts(2026)

        self.assertEqual(3001, events[0]["id"])
        self.assertEqual("2026-07-14", events[0]["start"])
        self.assertIn("effort-ajaxGetEfforts-411-2026", transport.requests[1]["url"])

    def test_delete_verifies_the_effort_no_longer_appears_in_my_efforts(self):
        transport = FakeTransport([EFFORT_DETAIL, json.dumps({"status": "success"}), CALENDAR_PAGE, "[]"])
        client = self.make_client(transport)

        result = client.delete_effort(3001, apply=True)

        self.assertEqual({"deleted": True, "id": 3001, "verified": True}, result)
        self.assertEqual("POST", transport.requests[1]["method"])
        self.assertIn("effort-ajaxGetEfforts-411-2026", transport.requests[3]["url"])

    def test_resolve_bug_posts_verified_form_values_and_rereads_the_result(self):
        transport = FakeTransport([RESOLVE_FORM, json.dumps({"status": "success"}), RESOLVED_BUG_DETAIL])
        client = self.make_client(transport)

        result = client.resolve_bug(
            bug_id=1001,
            resolution="fixed",
            resolved_build="trunk",
            comment="Fixed in the current branch.",
            apply=True,
        )

        self.assertEqual(
            {
                "resolved": True,
                "id": 1001,
                "status": "\u5df2\u89e3\u51b3",
                "resolution": "\u5df2\u89e3\u51b3",
                "resolvedBuild": "\u4e3b\u5e72",
                "commentWritten": True,
            },
            result,
        )
        self.assertEqual("POST", transport.requests[1]["method"])
        self.assertIn("bug-resolve-1001", transport.requests[1]["url"])
        self.assertEqual("fixed", transport.requests[1]["data"]["resolution"])
        self.assertEqual("trunk", transport.requests[1]["data"]["resolvedBuild"])
        self.assertEqual("tester", transport.requests[1]["data"]["assignedTo"])
        self.assertEqual("Fixed in the current branch.", transport.requests[1]["data"]["comment"])

    def test_resolve_bug_requires_apply_before_loading_the_form(self):
        transport = FakeTransport([])
        client = self.make_client(transport)

        with self.assertRaises(SafetyError):
            client.resolve_bug(
                bug_id=1001,
                resolution="fixed",
                resolved_build="trunk",
                comment="",
                apply=False,
            )

        self.assertEqual([], transport.requests)

    def test_parser_exposes_resolve_bug_command(self):
        args = _parser().parse_args(
            ["resolve-bug", "--id", "1001", "--comment", "Fixed in the current branch.", "--apply"]
        )

        self.assertEqual("resolve-bug", args.command)
        self.assertEqual(1001, args.id)
        self.assertEqual("fixed", args.resolution)
        self.assertEqual("trunk", args.resolved_build)
        self.assertTrue(args.apply)


if __name__ == "__main__":
    unittest.main()
