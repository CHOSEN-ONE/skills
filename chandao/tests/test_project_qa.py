import html
import io
import json
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from chandao_api import ChandaoClient, HttpResponse, _parser
from project_qa import ProjectQA, ProjectQAError, request_description, SECTIONS


def select(name, values, selected, extra=""):
    selected = [selected] if isinstance(selected, str) else selected
    opts = "".join(f"<option value='{key}' {'selected' if key in selected else ''}>{label}</option>"
                   for key, label in values.items())
    return f"<select name='{name}' {extra}>{opts}</select>"


class Server:
    """A paged project, with two products and independent builds and test requests."""
    base = "/pro/"

    def __init__(self):
        self.records = {"build": {}, "testtask": {}}
        self.writes = []
        self.allow_delete = True
        self.bad_readback = False
        self.strip_bold = False
        self.products = {"1": "RUM-APP", "2": "RUM-MP"}
        self.default = dict(p0=None, demo=None, scope="范围", impact="现有影响", config=None,
                            dependencies=None, risks="回归")
        for i in range(1, 4):
            self.records["build"][str(i)] = dict(product="2" if i == 2 else "1", name=f"v{i}",
                project="7", date="2026-11-20", builder="qa", desc="", filePath="", scmPath="")
        self.records["testtask"]["1"] = dict(product="1", project="7", name="已有", build="1", owner="qa",
            begin="2026-11-20", end="2026-11-21", status="wait", pri="3", desc=request_description(
                SimpleNamespace(**self.default)))

    def form(self, kind, obj, create, product, build):
        current = {} if create else self.records[kind][obj]
        def val(key, fallback=""):
            return current.get(key, fallback)
        lock = "disabled" if kind == "build" and not create else ""
        parts = [select("product", self.products, val("product", product), lock)]
        if kind == "testtask" or not create:
            parts.append(select("project", {"7": "项目"}, "7", lock))
        if kind == "testtask":
            parts.extend([select("owner", {"qa": "Q:测试员"}, val("owner", "qa")),
                select("build", {k: v["name"] for k, v in self.records["build"].items()}, val("build", build)),
                select("pri", {"3": "3"}, "3"), select("status", {"wait": "未开始"}, "wait"),
                select("mailto[]", {"a": "A", "b": "B"}, ["a", "b"], "multiple")])
            inputs = ["name", "begin", "end"]
        else:
            parts.append(select("builder", {"qa": "Q:测试员"}, "qa"))
            inputs = ["name", "date", "scmPath", "filePath"]
        for key in inputs:
            value = val(key, "2026-11-20" if key == "date" else "")
            parts.append(f"<input name='{key}' value='{html.escape(value, quote=True)}'>")
        parts.append(f"<textarea name='desc'>{html.escape(val('desc'))}</textarea>")
        return "<form method='post' id='dataform'>" + "".join(parts) + "</form>"

    def page(self, kind, page):
        items = list(self.records[kind].items())
        size = 1 if kind == "testtask" else max(1, len(items))
        rows = []
        for obj, r in items[(page-1)*size:page*size]:
            extra = f"<a href='/pro/testtask-create-{r['product']}-7-{obj}.html'>提交测试</a>" if kind == "build" else (
                f"<a href='/pro/build-view-{r['build']}.html'>版本</a>")
            if self.allow_delete:
                extra += (f"<a href='javascript:ajaxDelete(\"/pro/{kind}-delete-{obj}-yes.html\", "
                          f"\"taskList\", confirmDelete)'>删除</a>")
            rows.append(f"<tr data-id='{r['product']}'><td><a href='/pro/{kind}-view-{obj}.html'>"
                        f"{html.escape(r['name'])}</a><a href='/pro/{kind}-edit-{obj}.html'>编辑</a>{extra}</td></tr>")
        tableid = "buildList" if kind == "build" else "taskList"
        page_html = (select("product", self.products, "1") + "<a href='/pro/build-create-7.html'>创建</a>"
                     + f"<table id='{tableid}'>" + "".join(rows) + "</table>")
        if kind == "testtask":
            page_html += (f"<ul data-page='{page}' data-rec-total='{len(items)}' data-rec-per-page='1' "
                          f"data-link-creator='/pro/project-testtask-7-id_desc-{len(items)}-{{recPerPage}}-{{page}}.html'></ul>")
        return page_html

    def request(self, method, url, data=None, headers=None):
        route = url.split("/pro/")[1].removesuffix(".html")
        fields = route.split("-")
        kind = fields[0]
        if route == "project-index-no":
            body = "<div id='dropMenu' data-url='/pro/project-ajaxGetDropMenu-7-project-index-.html'></div>"
        elif fields[1] == "ajaxGetDropMenu":
            body = "<a href='/pro/project-task-7.html' title='项目'>项目</a>"
        elif kind == "project":
            body = self.page(fields[1], int(fields[-1]) if len(fields) > 3 else 1)
        elif fields[1] == "view":
            body = f"<title>{'TASK' if kind == 'testtask' else 'BUILD'} #{fields[2]} detail</title>"
        elif fields[1] == "delete":
            assert method == "GET" and fields[3] == "yes" and headers.get("X-Requested-With")
            del self.records[kind][fields[2]]
            self.writes.append((route, {}))
            body = json.dumps({"result": "success"})
        elif method == "GET":
            body = self.form(kind, fields[2], fields[1] == "create", fields[2], fields[-1])
        else:
            obj = fields[2] if fields[1] == "edit" else "9"
            if fields[1] == "edit" and kind == "build":
                assert "product" not in data and "project" not in data
            current = self.records[kind].setdefault(obj, {"project": "7"})
            current.update(data)
            if self.strip_bold:
                current["desc"] = current["desc"].replace("<strong>", "").replace("</strong>", "")
            if self.bad_readback:
                current["end"] = "2026-11-24"
            self.writes.append((route, data.copy()))
            body = '{"result":"success"}'
        return HttpResponse(200, url, {}, body)


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.srv = Server()
        self.qa = ProjectQA(ChandaoClient(Path.cwd(), transport=self.srv))
        self.parser = _parser()

    def call(self, *args, product="1"):
        return self.qa.run(self.parser.parse_args([args[0], "--project", "项目", "--product", product, *args[1:]]))

    def test_build_crud_and_scope(self):
        self.assertEqual([r["name"] for r in self.call("builds")], ["v1", "v3"])
        self.assertEqual(self.call("create-build", "--name", "新版", "--apply")["id"], 9)
        self.assertEqual(self.call("build", "--id", "9")["name"], "新版")
        self.assertTrue(self.call("edit-build", "--id", "9", "--name", "新名称", "--apply")["updated"])
        with self.assertRaises(ProjectQAError):
            self.call("delete-build", "--id", "9", "--apply", product="2")
        self.assertTrue(self.call("delete-build", "--id", "9", "--apply")["deleted"])

    def test_testtask_crud_template_paging_and_duplicate(self):
        args = ("create-testtask", "--name", "新提测", "--build", "v1", "--owner", "测试员",
                "--begin", "2026-11-20", "--end", "2026-11-23", "--scope", "校验 <输入>", "--apply")
        self.assertTrue(self.call(*args)["created"])
        payload = self.srv.writes[-1][1]
        self.assertIn("&lt;输入&gt;", payload["desc"])
        self.assertEqual(payload["desc"].count("<p>是</p>"), 2)
        for _, label in SECTIONS:
            self.assertIn(f"[{label}]", payload["desc"])
        self.assertEqual(self.call("testtask", "--id", "9")["build"], "1")
        with self.assertRaisesRegex(ProjectQAError, "同名"):
            self.call(*args)
        self.assertEqual(len(self.srv.writes), 1)
        self.assertTrue(self.call("edit-testtask", "--id", "1", "--risks", "仅验证边界", "--apply")["updated"])
        payload = self.srv.writes[-1][1]
        self.assertIn("现有影响", payload["desc"])
        self.assertIn("仅验证边界", payload["desc"])
        self.assertEqual(payload["mailto[]"], ["a", "b"])
        self.assertTrue(self.call("delete-testtask", "--id", "9", "--apply")["deleted"])

    def test_guards_and_unverified_writes(self):
        for args in [("delete-testtask", "--id", "1"), ("edit-testtask", "--id", "1", "--build", "2", "--apply"),
                     ("edit-testtask", "--id", "1", "--begin", "2026-11-25", "--apply")]:
            with self.assertRaises(ProjectQAError):
                self.call(*args)
        self.srv.allow_delete = False
        with self.assertRaisesRegex(ProjectQAError, "删除操作"):
            self.call("delete-testtask", "--id", "1", "--apply")
        self.assertEqual(self.srv.writes, [])
        self.srv.bad_readback = True
        with self.assertRaisesRegex(ProjectQAError, "回读不一致"):
            self.call("edit-testtask", "--id", "1", "--end", "2026-11-22", "--apply")
        self.assertEqual(len(self.srv.writes), 1)

    def test_fixed_answers_cannot_be_overridden_and_legacy_answers_are_normalized(self):
        for command in ("create-testtask", "edit-testtask"):
            extra = (["--build", "1", "--name", "新单", "--owner", "qa", "--scope", "范围",
                      "--begin", "2026-11-20", "--end", "2026-11-21"] if command == "create-testtask"
                     else ["--id", "1"])
            for flag in ("--p0", "--demo"):
                with self.subTest(command=command, flag=flag), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    self.call(command, *extra, flag, "否", "--apply")
        self.assertFalse(self.srv.writes)
        record = self.srv.records["testtask"]["1"]
        record["desc"] = record["desc"].replace("<p>是</p>", "<p>待确认</p>")
        self.call("edit-testtask", "--id", "1", "--end", "2026-11-23", "--apply")
        self.assertEqual(record["desc"].count("<p>是</p>"), 2)
        self.assertNotIn("待确认", record["desc"])

    def test_markdown_replacement_and_partial_edit_preserve_other_blocks(self):
        scope = "- **升级**后显示版本\n- 校验 `buildID`"
        self.call("edit-testtask", "--id", "1", "--replace-description", "--scope", scope,
                  "--impact", "[说明](https://example.org/qa)", "--apply")
        description = self.srv.records["testtask"]["1"]["desc"]
        for rich in ("<ul>", "<li><strong>升级</strong>", "<code>buildID</code>", 'href="https://example.org/qa"'):
            self.assertIn(rich, description)
        self.call("edit-testtask", "--id", "1", "--risks", "1. 检查旧数据\n2. 复测", "--apply")
        revised = self.srv.records["testtask"]["1"]["desc"]
        self.assertEqual(revised.split("[测试重点及风险]")[0], description.split("[测试重点及风险]")[0])
        self.assertIn("<ol>", revised)
        self.assertIn("<li>复测</li>", revised)

    def test_create_verifies_rendered_markdown_not_just_words(self):
        self.srv.strip_bold = True
        with self.assertRaisesRegex(ProjectQAError, "Markdown 格式不一致"):
            self.call("create-testtask", "--name", "复查", "--build", "1", "--owner", "qa",
                      "--begin", "2026-11-20", "--end", "2026-11-21", "--scope", "**升级**", "--apply")
        self.assertEqual(len(self.srv.writes), 1)
