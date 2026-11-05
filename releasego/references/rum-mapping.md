# RUM Mapping

Use this mapping for ReleaseGo rows that do not expose a repository URL. Page-provided URLs win over this reference.

For user requests like `根据3.0/悟空或者4.0/观云获取RUM涉及的应用名和配置名，以及git仓库地址`, answer from this file or run:

```bash
python <skill-root>/scripts/releasego_rum_inventory.py --line '3.0' --kind all --format markdown
```

Line aliases:

- `3.0`, `悟空`, `wukong`
- `4.0`, `观云`, `guanyun`

## 3.0 / 悟空 配置

| ReleaseGo name | Repository |
| --- | --- |
| schema-repo-app | `git@git.tingyun.com:3.0-operation/schema-repo-app.git` |
| schema-repo-common | `git@git.tingyun.com:3.0-operation/schema-repo-common.git` |
| schema-repo-browser | `git@git.tingyun.com:3.0-operation/schema-repo-browser.git` |
| schema-repo-mp | `git@git.tingyun.com:3.0-operation/schema-repo-mp.git` |

## 4.0 / 观云 配置

| ReleaseGo name | Repository |
| --- | --- |
| schema-repo-guanyun | `git@git.tingyun.com:4.0-operation/schema-repo-guanyun.git` |
| schema-repo-common | `git@git.tingyun.com:4.0-operation/schema-repo-common.git` |
| schema-repo-rum | `git@git.tingyun.com:4.0-operation/schema-repo-rum.git` |

## 3.0 / 悟空 RUM 应用

| ReleaseGo name | Repository | Jenkins | Notes |
| --- | --- | --- | --- |
| common-js-config | `git@git.tingyun.com:mp/mp-config-server.git` | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/common/job/common-js-config/` |  |
| app-dc-frontend | `git@git.tingyun.com:app3/app-dc-frontend.git` | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/app/job/app-dc-frontend/` |  |
| mp-api | `git@git.tingyun.com:mp/mp-report.git` | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/mp/job/mp-api/` |  |
| browser-api | `git@git.tingyun.com:eui-browser/browser-api.git` | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/browser/job/browser-api/` |  |
| app-deobfuscator-dubbo | `git@git.tingyun.com:app3/app-deobfuscator.git` | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/app/job/app-deobfuscator-dubbo/` | Same repository family as 4.0 `rum-dbg`; branch distinguishes version line. |
| app-api | `git@git.tingyun.com:app3/app-api.git` | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/app/job/app-api/` |  |
| common-rum-wrap | `git@git.tingyun.com:app3/rum-wrap.git` | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/common/job/common-rum-wrap/` |  |

### 悟空 rum-wrap 的 Git 组织方式

悟空的 `rum-wrap` 对应 ReleaseGo 应用名 `common-rum-wrap`。其中 `app-dc-wrap`、`browser-wrap`、`mp-wrap` 的创建方式取决于悟空版本：

- `3.9.0.24` 之前的版本：使用 Git submodule。
- `3.9.0.24` 及之后的版本（包含 `3.9.0.24`）：使用 Git subtree。

提取变更、检出代码或迁移这些模块前，分别确认源版本和目标版本的组织方式。跨此版本边界迁移时，需要处理 submodule 与 subtree 的目录及历史差异；submodule 的指针变更不等同于模块内的完整代码差异。此规则仅适用于悟空，不套用于观云的 `rum-wrap`。

## 4.0 / 观云 RUM 应用

| ReleaseGo name | Repository | Notes |
| --- | --- | --- |
| rum-wrap | `git@git.tingyun.com:o11y-rum/rum-wrap.git` | Split from 3.0 app. |
| rum-dc | `git@git.tingyun.com:o11y-rum/rum-dc.git` | Split from 3.0 app. |
| rum-dbg | `git@git.tingyun.com:app3/app-deobfuscator.git` | Same repository as 3.0 `app-deobfuscator-dubbo`; branch distinguishes version line. |
| guanyun-api / tingyun-observable-rum | `git@git.tingyun.com:guanyun-api-group/observable-api.git` | `tingyun-observable-rum` submodule/module inside guanyun-api context. |

## 悟空 / 观云共用二方包

二方包是应用依赖的公司内部代码库，单独维护仓库地址，不作为 ReleaseGo 应用或配置行列出。

| 二方包 | 适用产品 | Git 仓库地址 |
| --- | --- | --- |
| app-dc-common | 3.0 / 悟空、4.0 / 观云 | `http://git.tingyun.com/app3/app-dc-common` |

悟空和观云使用同一个 `app-dc-common` 仓库；共用仓库不代表各应用依赖同一个版本。

只有需求涉及修改该二方包时才获取源码。先根据目标应用的依赖声明或用户指定版本确认所需 ref；优先复用已存在且来源、版本匹配的本地仓库，缺少时再下载到当前任务工作目录。无法确定 ref 时询问用户，不默认选最新分支。普通发版查询、列清单或不涉及该包修改的任务不自动下载，也不因其在清单中就自动触发 Jenkins 构建或填写 ReleaseGo。

查询二方包清单（`--kind all` 也会包含 `dependencies`）：

```bash
python <skill-root>/scripts/releasego_rum_inventory.py --line 3.0 --kind dependencies --format markdown
python <skill-root>/scripts/releasego_rum_inventory.py --line 4.0 --kind dependencies --format json
```

## Unknown Items

If a requested app/config is not listed:

1. Check whether ReleaseGo details expose repository URL, group, branch, tag, or commit.
2. Check whether the item name appears as a module inside a listed repository.
3. If still unresolved, ask the user for the repository URL and expected branch/version line.
4. Add only verified mappings to this reference.

For Jenkins jobs, only the 3.0 / 悟空 RUM application URLs listed above are verified. Do not guess 4.0 / 观云 Jenkins jobs; ask the user for the job URL when needed.
