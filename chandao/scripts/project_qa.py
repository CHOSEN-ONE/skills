"""Project-scoped ZenTao builds and test requests, using the live page controls."""
import html
import json
import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, SubElement


class ProjectQAError(ValueError):
    pass


class Page(HTMLParser):
    """Small element tree for ZenTao's server-rendered tables and forms."""
    VOID = set("area base br col embed hr img input link meta param source track wbr".split())

    def __init__(self, source):
        super().__init__()
        self.root = Element("document")
        self.stack = [self.root]
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = SubElement(self.stack[-1], tag, {k: v or "" for k, v in attrs})
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag not in self.VOID:
            for i in range(len(self.stack) - 1, 0, -1):
                if self.stack[i].tag == tag:
                    del self.stack[i:]
                    break

    def handle_data(self, data):
        node = self.stack[-1]
        if len(node):
            node[-1].tail = (node[-1].tail or "") + data
        else:
            node.text = (node.text or "") + data


def text(node):
    return " ".join(" ".join(node.itertext()).split()) if node is not None else ""


def pick(options, value, field):
    value = str(value).strip()
    if value and value in options:
        return value
    matches = [k for k, v in options.items() if k and value and
               (v == value or (field in ("owner", "builder") and re.sub(r"^[A-Za-z]:\s*", "", v) == value))]
    if len(matches) != 1:
        raise ProjectQAError(f"{field} 无法唯一匹配，请提供表单中的完整名称或 ID。")
    return matches[0]


def options(select):
    return {o.get("value", ""): text(o) for o in select.iter("option") if "disabled" not in o.attrib}


def dataform(source):
    form = Page(source).root.find(".//form[@id='dataform']")
    if form is None or form.get("method", "").lower() != "post" or form.get("action"):
        raise ProjectQAError("当前页面缺少预期的原址 POST 表单。")
    values, choices, disabled = {}, {}, set()
    for node in form.iter():
        name = node.get("name")
        if not name:
            continue
        if "disabled" in node.attrib:
            disabled.add(name)
        if node.tag == "select":
            choices[name] = options(node)
            selected = [o.get("value", "") for o in node.iter("option") if "selected" in o.attrib]
            if "multiple" in node.attrib:
                values[name] = selected
            else:
                values[name] = next(iter(selected or choices[name]), "")
        elif node.tag == "textarea":
            values[name] = "".join(node.itertext())
        elif node.tag == "input" and node.get("type", "text").lower() not in (
            "file", "submit", "button", "reset", "image"
        ):
            if node.get("type") in ("radio", "checkbox") and "checked" not in node.attrib:
                continue
            val = node.get("value", "")
            if name.endswith("[]"):
                values.setdefault(name, []).append(val)
            else:
                values[name] = val
    uid = re.search(r"\bvar kuid\s*=\s*['\"]([a-fA-F0-9]+)['\"]", source)
    if uid:
        values["uid"] = uid[1]
    return values, choices, disabled


FIXED_SECTIONS = (
    ("p0", "自测是否通过: 按测试提供P0用例进行自测"), ("demo", "提测功能是否演示"),
)
EDITABLE_SECTIONS = (
    ("scope", "提测范围"), ("impact", "影响范围"), ("config", "配置变更"),
    ("dependencies", "部署依赖"), ("risks", "测试重点及风险"),
)
SECTIONS = FIXED_SECTIONS + EDITABLE_SECTIONS


def section_body(key, args):
    if key in ("p0", "demo"):
        return "<p>是</p>"
    from chandao_vendor.markdown2 import markdown
    value = getattr(args, key)
    if value is None:
        return None
    return markdown(value, safe_mode="escape", extras=["tables", "fenced-code-blocks"]).strip()


def request_description(args):
    return "".join(f"<p>[{label}]</p>" + (section_body(key, args) or "<p></p>")
                   for key, label in SECTIONS)


def markdown_structure(root):
    """Compare rich-text semantics, tolerating editor-added classes and wrappers."""
    tags = {"ul", "ol", "li", "strong", "em", "code", "pre", "a", "blockquote",
            "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr", "td", "th", "img"}
    result = []
    for node in root.iter():
        tag = {"b": "strong", "i": "em"}.get(node.tag, node.tag)
        if tag in tags:
            result.append((tag, node.get("href") or node.get("src") or "", text(node)))
    return result


def edit_description(source, args, require_template=True):
    """Set the fixed answers and retain untouched rich text in all other sections."""
    headers = [(key, f"[{label}]") for key, label in SECTIONS]
    spans = []
    for match in re.finditer(r"<p\b[^>]*>.*?</p\s*>", source, re.I | re.S):
        title = text(Page(match[0]).root)
        if title in dict(headers).values():
            spans.append((title, match.start(), match.end()))
    if [s[0] for s in spans] != [h for _, h in headers]:
        if not require_template:
            return source
        raise ProjectQAError("现有描述格式不同。要覆盖全文，请提供 --replace-description 和新的 --scope。")
    for i in reversed(range(len(spans))):
        body = section_body(headers[i][0], args)
        if body is not None:
            end = spans[i + 1][1] if i + 1 < len(spans) else len(source)
            source = source[:spans[i][2]] + body + source[end:]
    return source


def check_date(value):
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except (TypeError, ValueError):
        raise ProjectQAError("日期格式应为 YYYY-MM-DD。") from None


def register(sub):
    sub.add_parser("projects").set_defaults(qa=True)
    p = sub.add_parser("project-products")
    p.set_defaults(qa=True)
    p.add_argument("--project", required=True)
    for kind in ("testtask", "build"):
        for action in ("list", "get", "create", "edit", "delete"):
            cmd = kind + "s" if action == "list" else kind if action == "get" else action + "-" + kind
            p = sub.add_parser(cmd)
            p.set_defaults(qa=True, kind=kind, action=action)
            p.add_argument("--project", required=True)
            p.add_argument("--product", required=action != "list")
            if action in ("get", "edit", "delete"):
                p.add_argument("--id", type=int, required=True)
            if action in ("create", "edit", "delete"):
                p.add_argument("--apply", action="store_true")
            if action not in ("create", "edit"):
                continue
            p.add_argument("--name", required=action == "create")
            if kind == "testtask":
                for flag in ("build", "owner", "begin", "end"):
                    p.add_argument("--" + flag, required=action == "create")
                for flag, _ in FIXED_SECTIONS:
                    p.add_argument("--" + flag, choices=("是",), help="固定为是，可省略")
                for flag, _ in EDITABLE_SECTIONS:
                    p.add_argument("--" + flag, required=flag == "scope" and action == "create", help="Markdown 正文")
                if action == "edit":
                    p.add_argument("--replace-description", action="store_true")
                p.add_argument("--status")
                p.add_argument("--pri")
            else:
                for flag in ("builder", "date", "scm-path", "file-path", "desc", "branch"):
                    p.add_argument("--" + flag)


class ProjectQA:
    def __init__(self, client):
        self.client = client
        self.base = urlsplit(client.base_url).path.rstrip("/") + "/"

    def get(self, endpoint):
        return self.client._authenticated_request("GET", endpoint).body

    def projects(self):
        index = Page(self.get("project-index-no.html")).root
        menu = index.find(".//*[@id='dropMenu']")
        link = menu.get("data-url", "") if menu is not None else ""
        if not re.fullmatch(re.escape(self.base) + r"project-ajaxGetDropMenu-\d+-project-index-\.html", link):
            raise ProjectQAError("项目主页未提供项目选择器。")
        result = {}
        for a in Page(self.get(link[len(self.base):])).root.iter("a"):
            match = re.fullmatch(re.escape(self.base) + r"project-task-(\d+)\.html", a.get("href", ""))
            if match:
                result[match[1]] = a.get("title") or text(a)
        if not result:
            raise ProjectQAError("项目选择器未返回可用项目。")
        return result

    def products(self, project):
        root = Page(self.get(f"project-build-{project}.html")).root
        select = root.find(".//select[@name='product']")
        if select is None:  # Some project pages with no builds omit the filter.
            self.link(root, f"build-create-{project}.html")
            _, choices, _ = dataform(self.get(f"build-create-{project}.html"))
            result = choices.get("product", {})
        else:
            result = options(select)
        return {k: v for k, v in result.items() if k.isdecimal() and int(k) > 0}

    def link(self, node, endpoint):
        if not any(a.get("href") == self.base + endpoint for a in node.iter("a")):
            raise ProjectQAError(f"页面未提供 {endpoint} 操作，检查当前账号权限或接口变化。")
        return endpoint

    def listing(self, project, kind):
        endpoint = f"project-{kind}-{project}.html"
        table_id = "taskList" if kind == "testtask" else "buildList"
        rows, pages, total = {}, 0, None
        while True:
            root = Page(self.get(endpoint)).root
            table = root.find(f".//table[@id='{table_id}']")
            if pages == 0:
                first = root
            if table is None:
                # Only a recognized project list and its explicit empty state prove absence.
                empty = any("table-empty-tip" in n.get("class", "").split() for n in root.iter())
                if empty and not pages and root.find(".//*[@id='currentItem']") is not None:
                    self.link(root, f"build-create-{project}.html" if kind == "build" else f"testtask-create-0-{project}.html")
                    return {}, first
                raise ProjectQAError("列表结构改变或无权访问，无法判断记录是否存在。")
            for row in table.iter("tr"):
                if "group-summary" in row.get("class", "").split() or row.find("td") is None:
                    continue
                refs = [(m[1], text(a)) for a in row.iter("a") if
                        (m := re.fullmatch(re.escape(self.base) + kind + r"-view-(\d+)\.html", a.get("href", "")))]
                if not refs or len({i for i, _ in refs}) != 1 or not row.get("data-id", "").isdecimal():
                    raise ProjectQAError("列表行缺少产品或对象标识，无法完成全量核对。")
                obj, name = refs[-1]
                if obj in rows:
                    raise ProjectQAError("分页结果有重复 ID，请重新查询。")
                summary = {"id": int(obj), "name": name, "product": row.get("data-id"), "project": project}
                if kind == "testtask":
                    build_ids = [m[1] for a in row.iter("a") if
                                 (m := re.fullmatch(re.escape(self.base) + r"build-view-(\d+)\.html", a.get("href", "")))]
                    summary["build"] = next(iter(build_ids), None)
                rows[obj] = (summary, row)
            pages += 1
            pager = root.find(".//*[@data-link-creator][@data-rec-total]")
            if pager is None:
                if pages != 1 or kind == "testtask" and rows:
                    raise ProjectQAError("缺少分页信息。")
                break
            try:
                count = int(pager.get("data-rec-total"))
                size = int(pager.get("data-rec-per-page"))
                current = int(pager.get("data-page"))
            except (ValueError, TypeError):
                raise ProjectQAError("无效的分页信息。") from None
            if pages != current or size <= 0 or count < 0 or total not in (None, count):
                raise ProjectQAError("分页期间记录数或页码发生变化，请重新查询。")
            total = count
            if pages * size >= total:
                if len(rows) != total:
                    raise ProjectQAError("返回的记录数与分页总数不符。")
                break
            template = pager.get("data-link-creator")
            if not re.fullmatch(re.escape(self.base) + f"project-{kind}-{project}-" +
                                r"[a-zA-Z0-9_,-]+-\{recPerPage\}-\{page\}\.html", template):
                raise ProjectQAError("未知的分页链接。")
            endpoint = template[len(self.base):].format(recPerPage=size, page=pages + 1)
        return rows, first

    def detail(self, kind, item):
        obj = item["id"]
        root = Page(self.get(f"{kind}-view-{obj}.html")).root
        prefix = "TASK" if kind == "testtask" else "BUILD"
        if not re.match(rf"^{prefix}\s*#\s*{obj}\b", text(root.find(".//title")), re.I):
            raise ProjectQAError("详情页未回显所请求的 ID。")
        fields = {}
        for row in root.iter("tr"):
            label, val = row.find("th"), row.find("td")
            if label is not None and val is not None:
                fields[text(label)] = text(val)
        if kind == "testtask":
            for node in root.iter("div"):
                if "article-content" in node.get("class", "").split():
                    fields["描述"] = text(node)
                    break
        return dict(item, fields=fields), root

    def delete(self, kind, item, row):
        obj = item["id"]
        direct = f"{kind}-delete-{obj}-yes.html"
        intro = f"{kind}-delete-{obj}.html"
        _, detail = self.detail(kind, item)
        hrefs = [a.get("href", "") for node in (row, detail) for a in node.iter("a")]
        exact = re.escape(self.base + direct)
        ajax = any(re.fullmatch(r"""javascript:ajaxDelete\((["'])""" + exact + r"""\1,\s*(["'])\w+\2,\s*\w+\);?""", h)
                   for h in hrefs)
        if not ajax:
            if self.base + intro not in hrefs:
                raise ProjectQAError("当前列表和详情均未提供该记录的删除操作。")
            confirm = self.get(intro)
            if not (re.search(r"\bconfirm\s*\(", confirm) and
                    re.search(r"""['"]""" + exact + r"""['"]""", confirm)):
                raise ProjectQAError("服务端未返回对应记录的删除确认链接。")
        self.client.qa_write("GET", direct, ajax=True)
        remaining, _ = self.listing(item["project"], kind)
        if str(obj) in remaining:
            raise ProjectQAError("删除后仍能读到该记录，请核对后再操作。")
        return {"deleted": True, **item}

    def build_choice(self, project, product, value):
        builds, _ = self.listing(project, "build")
        choices = {i: b["name"] for i, (b, _) in builds.items() if b["product"] == product}
        obj = pick(choices, value, "build")
        return obj, builds[obj][1]

    def branch(self, source, product, values, choices):
        groups = re.search(r"\bproductGroups\s*=\s*(\{[^\n;]*\})\s*;", source)
        if not groups:
            raise ProjectQAError("找不到目标产品的分支定义。")
        try:
            group = json.loads(groups[1])[product]
            old = str(group["branch"])
            if not old.isdecimal():
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ProjectQAError("目标产品分支定义不可用。") from None
        choices.pop("branch", None)
        values.pop("branch", None)
        if group.get("type") != "normal":
            root = Page(self.get(f"branch-ajaxGetBranches-{product}-{old}.html")).root
            select = root.find(".//select[@name='branch']")
            if select is None:
                raise ProjectQAError("目标产品分支列表不可用。")
            choices["branch"] = options(select)
            selected = select.find(".//option[@selected]")
            values["branch"] = selected.get("value") if selected is not None else old
            pick(choices["branch"], values["branch"], "branch")

    def run(self, args):
        action = getattr(args, "action", "")
        if action in ("create", "edit", "delete") and not args.apply:
            raise ProjectQAError("写操作需要 --apply。")
        projects = self.projects()
        if args.command == "projects":
            return projects
        try:
            project = pick(projects, args.project, "project")
        except ProjectQAError as error:
            raise ProjectQAError("请选择 RUM-产品迭代-2026、RUM-客户支持-2026、观云-RUM-2025，"
                                 "也可手动输入当前可见项目的完整名称或 ID。") from error
        products = self.products(project)
        if args.command == "project-products":
            return products
        product = pick(products, args.product, "product") if args.product else None
        kind = args.kind
        listing, page = self.listing(project, kind)
        scoped = {k: pair for k, pair in listing.items() if not product or pair[0]["product"] == product}
        if action == "list":
            return [r for r, _ in scoped.values()]
        if action != "create":
            if str(args.id) not in scoped:
                raise ProjectQAError("目标 ID 不在指定项目和产品下。")
            item, row = scoped[str(args.id)]
            if action == "get":
                return self.detail(kind, item)[0]
            if action == "delete":
                return self.delete(kind, item, row)
        if args.name is not None and not args.name.strip():
            raise ProjectQAError("名称不能为空。")
        build = None
        if kind == "testtask" and args.build is not None:
            build, build_row = self.build_choice(project, product, args.build)
        target_name = args.name.strip() if args.name else item["name"]
        target_build = build if build is not None or action == "create" else item.get("build")
        if any(r["name"] == target_name and r["id"] != getattr(args, "id", None)
               and (kind == "build" or r["build"] == target_build) for r, _ in scoped.values()):
            raise ProjectQAError("目标范围内已有同名记录，请核对已有 ID。")
        if action == "edit":
            endpoint = self.link(row, f"{kind}-edit-{args.id}.html")
        elif kind == "build":
            endpoint = self.link(page, f"build-create-{project}.html")
        else:
            endpoint = self.link(build_row, f"testtask-create-{product}-{project}-{build}.html")
        source = self.get(endpoint)
        values, choices, disabled = dataform(source)
        required = {"product", "name", "desc"}
        required.update(("build", "project", "owner", "begin", "end", "status", "pri") if kind == "testtask"
                        else ("builder", "date", "scmPath", "filePath"))
        if not required <= values.keys():
            raise ProjectQAError("表单字段不完整，请重新核实接口。")
        if action == "edit" and (values["product"] != product or values.get("project") != project
                                 or values["name"] != item["name"]):
            raise ProjectQAError("编辑表单与列表中的目标不一致。")
        if action == "create" and kind == "build" and values["product"] != product:
            self.branch(source, product, values, choices)
        if action == "create" and kind == "testtask" and (values["product"], values["project"], values["build"]) != (
                product, project, build):
            raise ProjectQAError("提测表单与所选版本的项目或产品不一致。")
        changes = {}
        if args.name is not None:
            changes["name"] = args.name.strip()
        if kind == "build":
            for flag, field in (("builder", "builder"), ("date", "date"), ("scm_path", "scmPath"),
                                ("file_path", "filePath"), ("branch", "branch"), ("desc", "desc")):
                value = getattr(args, flag)
                if value is not None:
                    changes[field] = html.escape(value).replace("\n", "<br>") if field == "desc" else value
            if action == "create":
                changes["product"] = product
        else:
            for field in ("owner", "begin", "end", "status", "pri"):
                if getattr(args, field) is not None:
                    changes[field] = getattr(args, field)
            if build is not None:
                changes["build"] = build
            if action == "create" or args.replace_description:
                if not args.scope or not args.scope.strip():
                    raise ProjectQAError("重写提测描述时请提供提测范围和完整简要内容。")
                changes["desc"] = request_description(args)
            else:
                section_requested = any(getattr(args, k) is not None for k, _ in SECTIONS)
                if changes or section_requested:
                    changes["desc"] = edit_description(values["desc"], args, require_template=section_requested)
        if not changes:
            raise ProjectQAError("请指定要修改的字段。")
        before = values.copy()
        for field, value in changes.items():
            if field not in values:
                raise ProjectQAError(f"表单未提供字段 {field}。")
            if field in choices:
                value = pick(choices[field], value, field)
            if field in disabled and value != values[field]:
                raise ProjectQAError(f"当前表单已锁定 {field}，无法修改。")
            values[field] = value
        for field in (("begin", "end") if kind == "testtask" else ("date",)):
            check_date(values[field])
        if kind == "testtask" and (values["begin"] > values["end"] or not values["owner"]):
            raise ProjectQAError("请提供负责人，并确保结束日期不早于开始日期。")
        if action == "edit" and before == values:
            return {"updated": False, "unchanged": True, **self.detail(kind, item)[0]}
        payload = {k: v for k, v in values.items() if k not in disabled}
        self.client.qa_write("POST", endpoint, payload, ajax=kind == "build")
        after, _ = self.listing(project, kind)
        matches = [(i, r) for i, (r, _) in after.items() if r["product"] == product and r["name"] == values["name"]
                   and (kind != "testtask" or r["build"] == target_build)
                   and (i not in listing if action == "create" else i == str(args.id))]
        if len(matches) != 1:
            raise ProjectQAError("已提交，列表未唯一确认结果。请先回读，勿重复提交。")
        obj, verified = matches[0]
        detail, detail_page = self.detail(kind, verified)
        edit_ep = f"{kind}-edit-{obj}.html"
        if not any(a.get("href") == self.base + edit_ep for n in (after[obj][1], detail_page) for a in n.iter("a")):
            raise ProjectQAError(f"已提交，ID {obj}，缺少编辑表单，无法核对提交字段。")
        actual, _, _ = dataform(self.get(edit_ep))
        verify = required | {"project"}
        if "branch" in values:
            verify.add("branch")
        verify.update(changes)
        for field in verify:
            wanted = values.get(field, project if field == "project" else "")
            observed = actual.get(field)
            if field == "desc":
                wanted_root, observed_root = Page(wanted).root, Page(observed or "").root
                if kind == "testtask" and (action == "create" or wanted != before.get("desc")):
                    if markdown_structure(wanted_root) != markdown_structure(observed_root):
                        raise ProjectQAError(f"已提交，ID {obj} 的描述回读后 Markdown 格式不一致，请核对。")
                wanted, observed = text(wanted_root), text(observed_root)
            if observed != wanted:
                raise ProjectQAError(f"已提交，ID {obj} 的 {field} 回读不一致，请核对。")
        return {("created" if action == "create" else "updated"): True, **detail}
