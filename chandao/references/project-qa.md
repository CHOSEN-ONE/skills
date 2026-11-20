# 项目测试单与版本

从工作区运行 `python -B <skill-root>/scripts/chandao_api.py --workspace . <command>`。下表为命令后半段。项目、产品、版本和负责人都支持准确名称或实时选项的 ID/账号。测试单与版本本身的编辑、删除使用数字 ID。

| 用途 | 命令示例（尖括号为待填值） |
| --- | --- |
| 可见项目、项目产品 | `projects`、`project-products --project <项目>` |
| 全量列表 | `testtasks --project <项目> --product <产品>`、`builds --project <项目> --product <产品>`，省略产品可看整个项目 |
| 单条详情 | `testtask --project <项目> --product <产品> --id <测试单ID>`、`build --project <项目> --product <产品> --id <版本ID>` |
| 创建版本 | `create-build --project <项目> --product <产品> --name <版本名> --apply` |
| 编辑、删除版本 | `edit-build --project <项目> --product <产品> --id <版本ID> --desc "本次变更摘要" --apply`、`delete-build --project <项目> --product <产品> --id <版本ID> --apply` |
| 新建测试单 | `create-testtask --project <项目> --product <产品> --name <测试单名称> --build <版本ID> --owner <负责人> --begin <YYYY-MM-DD> --end <YYYY-MM-DD> --scope "提测范围" --risks "重点验证项" --apply` |
| 编辑、删除测试单 | `edit-testtask --project <项目> --product <产品> --id <测试单ID> --end <YYYY-MM-DD> --apply`、`delete-testtask --project <项目> --product <产品> --id <测试单ID> --apply` |

版本还可提供 `--builder`、`--date`、`--branch`、`--scm-path`、`--file-path` 和 `--desc`。创建时从目标产品表单取默认值。已有版本的锁定字段只用于核对归属。测试单可调整名称、关联版本、负责人、起止日期、优先级、状态和描述。先查项目下的产品和版本再选，保留现有抄送人。

## 写给测试人员的描述

七个方括号标题固定。自测和演示两项始终填写“是”，调用时省略 `--p0` 和 `--demo` 即可。后五项各自接收 Markdown 正文，单个要点可写一句话，多个要点用列表，配置键或版本号用行内代码。客户端通过 HTTP 把渲染后的富文本写入禅道。未知内容可以留空，“无变更”须有依据。

```markdown
[自测是否通过: 按测试提供P0用例进行自测]
是
[提测功能是否演示]
是
[提测范围]
- 支持按 `buildID` 查询指定版本。

[影响范围]
- 版本列表及详情页。

[配置变更]

[部署依赖]

[测试重点及风险]
1. **已有版本**仍可查询。
2. 查询不存在的版本时给出明确提示。
```

后五段依次对应 `--scope`、`--impact`、`--config`、`--dependencies`、`--risks`。多行 Markdown 作为一个参数传入，保留实际换行。局部编辑只更新指定的正文，并把可识别七段模板的前两项统一为“是”。原文是其他格式且用户要求重写全文时，用 `--replace-description --scope ...` 并提供需保留的各段内容。

## HTTP 契约

以下路径相对于实例的 `/pro/`。项目和产品 ID 由实时选项解析。只消费受信任路径下、与当前目标 ID 一致的链接。

| 页面或动作 | 路径和字段 |
| --- | --- |
| 项目选择器 | GET `project-index-no.html` → 读取 `#dropMenu[data-url]` 的 `project-ajaxGetDropMenu-{current}-project-index-.html` → 解析项目名称及 `project-task-{project}.html` 的 ID |
| 版本及产品 | GET `project-build-{project}.html`，产品来自 `select[name=product]`，版本来自 `#buildList tr[data-id]`（data-id 是产品 ID） |
| 项目测试单 | GET `project-testtask-{project}.html`，按 `#taskList tr[data-id]` 解析产品、测试单及关联版本，从服务端 pager 链接逐页读取并核对记录总数 |
| 详情 | GET `testtask-view-{id}.html` 或 `build-view-{id}.html`，核对详情 ID，读取基本信息及描述 |
| 创建、编辑版本 | GET 表单、POST 同址，`build-create-{project}.html` / `build-edit-{id}.html`。字段包括 product、可选 branch、name、builder、date、scmPath、filePath、desc；编辑表单另有 project。跨产品创建时按 productGroups 读取目标默认分支，分支型产品从 `branch-ajaxGetBranches-{product}-{oldBranch}.html` 取选项 |
| 创建、编辑测试单 | 项目入口为 `testtask-create-0-{project}.html`。客户端从目标版本行取 `testtask-create-{product}-{project}-{build}.html`，或由当前测试单取 `testtask-edit-{id}.html`。GET 表单、POST 同址。字段包括 product、project、build、owner、pri、begin、end、status、name、desc、mailto[]；编辑表单另有 comment |
| 删除版本 | 实例列表提供 `ajaxDelete("/pro/build-delete-{id}-yes.html", ...)`，已核实 my.full.js 使用带 AJAX 标头的 GET。此请求会删除数据 |
| 删除测试单 | 优先从该行的 ajaxDelete 操作取得 `testtask-delete-{id}-yes.html`。若详情给出 `testtask-delete-{id}.html`，只接受服务器确认页中与原 ID 匹配的 yes 链接。确认请求同样按写入处理。当前账号所查记录未展示删除入口；缺少权限时客户端停止。此路径另与[禅道开源项目的列表模板](https://github.com/easysoft/zentaopms/blob/2422e1f0d4eacf1cfcbdf2ed7e1bd4f894d550f5/module/project/view/testtask.html.php)及[删除控制器](https://github.com/easysoft/zentaopms/blob/2422e1f0d4eacf1cfcbdf2ed7e1bd4f894d550f5/module/testtask/control.php)核对过 |

每次业务写入只发一次。创建后按项目、产品、名称、关联版本和新 ID 查找，编辑按原 ID 查找，再读取详情和编辑表单核实字段。删除后全量回读项目列表。遇到超时、回读不符或权限变化，先查询现状再判断下一步。

2026-11-20 已用三个常用项目验证真实列表、分页、产品、详情和编辑表单。真实表单组装已在发送前拦截验证；创建、编辑和删除的完整提交与回读通过模拟服务测试。
