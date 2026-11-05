---
name: releasego
description: "Use when Tingyun internal ReleaseGo private-release work needs a portable workflow across Windows/macOS: ReleaseGo release queries and filling, GitLab compare/change extraction, Jenkins RUM app builds, RUM app/config/dependency inventory by 3.0/悟空 or 4.0/观云, 二方包仓库, app-dc-common, migration support, credential fallback, CDP browser setup, 发版系统, 参与发版, 变更应用, 变更配置, or 填写发版."
---

# ReleaseGo

Use this skill for Tingyun internal private-release work around ReleaseGo, GitLab, Jenkins, and RUM app/config release workflows.

Use this portable cross-platform variant. Do not assume a user-specific install path, a Windows-only launcher, or a fixed Chrome path. Resolve paths relative to this skill directory, environment variables, or the current workspace.

## Portable Setup

- Treat `<skill-root>` as this skill directory, the parent of `SKILL.md`.
- Resolve the work directory from local `workDir`, then `RELEASEGO_WORK_DIR`, otherwise `<workspace>/.releasego`. Compare caches and tag temporary repositories use it; explicit `--repo-cache`, `--work-dir` and `--out` take precedence. Put requested reports under that directory unless the user specifies another destination.
- Use `RELEASEGO_BROWSER_CDP` for the AI browser CDP endpoint, defaulting to `http://127.0.0.1:9222`.
- Use `RELEASEGO_CHROME_PATH` when Chrome cannot be discovered automatically.
- Use `~/.releasego/browser-profile` as the default dedicated browser profile when a browser must be started.
- Do not depend on a machine-specific Windows browser launcher script; not every Windows machine has one, and Chrome install paths differ.

Use Python 3.10+ and Git on both platforms; SSH repository URLs also need a configured SSH client/key. Only UI fallback needs Chrome and the browser automation tooling. The scripts use the Python standard library.

- Windows: verify `py -3 --version` or a real `python --version`; a WindowsApps alias is not a usable interpreter. Run `py -3 -B "<skill-root>/scripts/releasego_doctor.py"` (or use the verified Python executable).
- macOS: verify `python3 --version` and `git --version`, then run `python3 -B "<skill-root>/scripts/releasego_doctor.py"`. Do not assume `python` exists.
- In subsequent examples, replace `python` with that verified interpreter. Quote paths containing spaces. `workDir` and `chromePath` accept `~` and environment-variable expansion; explicit CLI paths accept `~`.
- Use UTF-8 mode (`PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`) and `-B` when maintaining or testing the skill. Git subprocess text is decoded as UTF-8; generated patches preserve original bytes and line endings.

## Local Configuration

Credentials are local machine data and must never be packaged into the shared `.skill` file.

Read credentials and optional endpoint overrides in this order:

1. `<skill-root>/config.local.json`
2. environment variables
3. stop and ask the user to configure credentials

Create local config by copying `<skill-root>/config.example.json` to `<skill-root>/config.local.json` after installing the skill. The three systems share the same LDAP username/password.

Supported environment variables:

- `TINGYUN_USERNAME`
- `TINGYUN_PASSWORD`
- `RELEASEGO_BASE_URL`
- `RELEASEGO_GITLAB_BASE_URL`
- `RELEASEGO_GITLAB_ALLOW_HTTP` (`true`/`false` or `1`/`0`; default `false`)
- `RELEASEGO_JENKINS_BASE_URL`
- `RELEASEGO_BROWSER_CDP`
- `RELEASEGO_CHROME_PATH`
- `RELEASEGO_WORK_DIR`

Never print usernames, passwords, authentication headers or cookies in logs, reports, errors, screenshots, or debug output. Use `scripts/releasego_config.py --require-credentials --json` when a workflow needs to verify credentials are configured. Do not dump raw session/config objects or bypass the session's output redactor.

## Authentication Transport And Output

- HTTPS with certificate verification remains the default. ReleaseGo and Jenkins always require it. Every client restricts requests and redirects to its own configured origin (scheme, host and port); embedded URL credentials are rejected. A job/build URL on another host is not authorization to send LDAP credentials there.
- For a GitLab deployment that only provides HTTP, an explicitly authorized local exception is supported: set `gitlabBaseUrl` to the exact HTTP origin and `gitlabAllowHttp` to JSON `true` in `config.local.json`, or set both `RELEASEGO_GITLAB_BASE_URL` and `RELEASEGO_GITLAB_ALLOW_HTTP=true`. Local values take precedence, including explicit `false`. This exception permits unencrypted GitLab authentication; origin checks and output redaction do not encrypt the connection. Preserve an existing authorization instead of repeatedly asking during the same task.
- The shared template keeps HTTPS and `gitlabAllowHttp=false`. There is no automatic HTTPS-to-HTTP fallback, including when the exception is enabled; requests and redirects must still match the configured scheme, host and port. A TLS failure with an HTTPS configuration is a stop point, not permission to disable certificate verification or change the scheme.
- HTTP API and Git/SSH can both be used in an authorized HTTP-only deployment. For Tingyun's known SSH service, use the existing `git.tingyun.com` host configuration with port 2222, or an explicit URL such as `ssh://git@git.tingyun.com:2222/app3/app-api.git`. Port 2222 is SSH, not an HTTP/HTTPS API endpoint. Keep host-key verification enabled.
- The same configured transport policy applies to browser autofill and manual login; browser fallback must not bypass the policy. Local browser CDP at `http://127.0.0.1:9222` is a control endpoint, not an LDAP login endpoint.
- `scripts/releasego_security.py` centralizes origin validation, redirect checks and output redaction. Session output masks configured credentials and common encodings, sensitive fields, `name`/`value` parameter pairs, and recognizable credential text. Redact complete text before truncation. Preserve internal API data for application matching; do not print it directly.

## Browser And Login Baseline

- Apply the shared `ai-browser` baseline before browser work when available.
- For ReleaseGo JSON API work, prefer browserless HTTP login with `scripts/releasego_http_session.py` before opening a browser.
- For GitLab JSON API work, prefer browserless LDAP callback login with `scripts/releasego_gitlab_session.py`.
- For Jenkins JSON/log API work, prefer LDAP Basic Auth with `scripts/releasego_jenkins_session.py`.
- Default to lazy auth: assume ReleaseGo, GitLab, and Jenkins are already logged in; open the target page or call the target API first.
- If the page redirects to login or an API returns an unauthenticated signal, wait briefly for browser autofill.
- If autofill does not populate credentials, load username/password from `scripts/releasego_config.py` and fill the login form.
- After login recovery, retry the original page/API action once. Stop if it is still unauthenticated.
- Treat `401`, `403`, login redirects, login HTML instead of JSON, or a browser page sitting on a login URL as unauthenticated.
- Use the browser only for UI fallback, new interface discovery, MFA/captcha/account-selection flows, or a Jenkins build submission test the user explicitly authorizes.

## Browser Discovery

1. Connect to `RELEASEGO_BROWSER_CDP` or `http://127.0.0.1:9222`.
2. If CDP is unavailable, find Chrome:
   - first `RELEASEGO_CHROME_PATH`;
   - then system and user Chrome install paths on Windows (`Program Files` and `LOCALAPPDATA`);
   - then `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` and the same path under the user's `~/Applications` on macOS.
3. Start Chrome with `--remote-debugging-port=9222` and `--user-data-dir=<home>/.releasego/browser-profile` only when browser startup is required by the local agent environment.
4. If browser startup is not supported by the current agent, stop and tell the user to start a Chrome instance with remote debugging enabled.

Run `python <skill-root>/scripts/releasego_doctor.py` for a read-only environment check.

## Quick Reference

- ReleaseGo browserless login: `POST /doLogin` with JSON body `username`, `password`; expected success is `code: 200`, `msg: OK`
- GitLab browserless login: `GET /users/sign_in` to read `authenticity_token`, then `POST /users/auth/ldapmain/callback` with form fields `authenticity_token`, `username`, `password`, `remember_me=0`
- GitLab current user: `GET /api/v4/user`
- GitLab project search: `GET /api/v4/projects?search=<query>&simple=true&per_page=<n>`
- GitLab project detail: `GET /api/v4/projects/<urlencoded namespace/project>`
- GitLab compare: `GET /api/v4/projects/<urlencoded namespace/project>/repository/compare?from=<base>&to=<head>`
- GitLab refs: `GET /api/v4/projects/<urlencoded namespace/project>/repository/branches|tags|commits`
- GitLab commit diff: `GET /api/v4/projects/<urlencoded namespace/project>/repository/commits/<sha>/diff`
- Git tag creation: prefer `scripts/releasego_git_tag.py` using Git protocol; GitLab session API tag creation returned `404 Project Not Found` on this instance
- Jenkins auth test: Basic Auth `GET /whoAmI/api/json`
- Jenkins job parameters: Basic Auth `GET <jobUrl>/api/json?tree=nextBuildNumber,property[parameterDefinitions[name,type,description,defaultParameterValue[value]]],actions[parameterDefinitions[name,type,description,defaultParameterValue[value]]]`
- Jenkins queue: Basic Auth `GET /queue/api/json` and `GET /queue/item/<id>/api/json`
- Jenkins executors: Basic Auth `GET /computer/api/json`
- Release lookup: `GET /view/release/getReleaseList?page=1&limit=100&releaseVersion=<version>&status=&releaseForkName=`
- Config rows: `GET /view/release/getReleaseConfigList?releaseVersionId=<id>&page=1&limit=200`
- Config save: `POST /view/release/SaveOrUpdateReleaseConfig` with JSON body `id`, `gitId`, `gitTag`, `releaseVersionId`
- App rows: `GET /view/application/getApplicationList?releaseVersionId=<id>&page=1&limit=100`
- Plan rows: `GET /view/plan/getPlanList?releaseVersionId=<id>&page=1&limit=200`
- Product/app metadata: `GET /view/application/getProductList`, `GET /view/application/getApplicationListByProduct?productCode=<code>`, `GET /view/application/getApplicationVersionListByApplicationId?applicationId=<id>`, `GET /view/application/getApplicationBuildIdListByApplicationId?buildId=<applicationVersionId>`
- ReleaseGo app/config writes require explicit confirmation in helper scripts: `save-config`, `add-plan`, `confirm-plan`, `replace-app`, `save-app`, `delete-app`
- Jenkins job status: `GET <jobUrl>/api/json?tree=nextBuildNumber,lastBuild[number,result,building,url,timestamp,duration],builds[number,result,building,url,timestamp,duration]{0,8}`
- Jenkins build status: `GET <buildUrl>/api/json?tree=number,url,building,result,duration,estimatedDuration,timestamp,actions[parameters[name,value]],executor[currentExecutable[number,url]]`
- Jenkins progressive log: `GET <buildUrl>/logText/progressiveText?start=<offset>`
- Jenkins build trigger: Basic Auth `POST <jobUrl>/buildWithParameters` with form fields such as `TAG=<tag>` and optional `sonar.skip=false`; helper requires `--confirm-trigger yes`
- Only fill ReleaseGo when release status is `0` (`等待集成`).

## Product Identity And Safe Application Replacement

These rules apply to every product line, including new/custom lines:

- Resolve product identity from `/getProductList` and the application's metadata. Submit the exact `code` in `product` / `productCode`; `name` / `productName` are display text only. Do not guess codes from names, normalize case, or hardcode a product list.
- A successful response or `already participating` message is not proof of participation. Re-read plans and require a unique row for the exact release ID and product code. Use `data`, not the sometimes-zero `count` field, to inspect rows.
- Prefer `replace-app` for application replacement. It checks the release, application membership, visible plan, new/old build metadata and recovery snapshot before deleting anything. A duplicate-application response alone is never authorization to immediately delete the old row.
- Preserve existing rows when the required plan is missing, malformed or inconsistent. Permission to ignore an erroneous record does not remove the backend dependency: proceed if a separate valid required plan exists; otherwise report the concrete blocker without repeated confirmation requests.
- Delete/add is not atomic. On an ambiguous write result, read back first; on a failed replacement, attempt a verified single restore only when prerequisites remain valid, then report the actual remaining state and snapshot path. Do not guess record IDs, change other products, or reset an entire release to recover one application.

Read [the fill workflow](references/releasego-fill-after-build.md) before any participation or application mutation. `save-app` and `delete-app` remain low-level commands for explicit operations; do not hand-chain them as a substitute for the replacement preflight.

## Git Worktree Checkout Safety

For a ReleaseGo worktree, a directory at the intended commit is not enough. Before reporting it ready, its local branch must track the intended remote branch and `git pull --ff-only` must succeed.

1. Resolve the remote ref before creating a worktree:

   ```bash
   git ls-remote --heads origin "refs/heads/<remote-ref>"
   ```

   If it exists, use `<remote-ref>` as the local branch name by default. Do not silently turn `release/2.5.0-2` into `2.5.0-2`: Git's default `push.default=simple` then rejects a plain `git push` because the names differ.

2. Worktree caches may have no `remote.origin.fetch`. Inspect it, then configure and fetch the required remote-tracking ref before setting upstream:

   ```bash
   git config --get-all remote.origin.fetch
   git config --replace-all remote.origin.fetch "+refs/heads/<remote-ref>:refs/remotes/origin/<remote-ref>"
   git fetch --prune origin
   git show-ref --verify --quiet "refs/remotes/origin/<remote-ref>"
   ```

   Use the scoped refspec above for a release checkout; do not assume `git fetch origin <remote-ref>` creates `origin/<remote-ref>` when `remote.origin.fetch` is unset.

3. Create and validate a remote-backed worktree. If the local branch does not already exist:

   ```bash
   git worktree add -b <remote-ref> <target-path> "origin/<remote-ref>"
   git -C <target-path> branch --set-upstream-to="origin/<remote-ref>" <remote-ref>
   git -C <target-path> status -sb
   git -C <target-path> pull --ff-only
   ```

   If a different local name is necessary, set its upstream explicitly and use `git push origin HEAD:refs/heads/<remote-ref>`; do not change its upstream to a same-named but unintended remote branch.

4. When the remote release branch does not exist, a local branch has no valid upstream. State this clearly instead of claiming `git pull` will work. After the user authorizes publication, push it with `git push -u origin <local-ref>` and then verify the upstream.

5. If `git status -sb` shows both ahead and behind, do not merge, rebase, reset, or push automatically. Diagnose first:

   ```bash
   git -C <target-path> fetch --prune origin
   git -C <target-path> rev-list --left-right --count HEAD..."origin/<remote-ref>"
   git -C <target-path> log --left-right --cherry-pick --oneline HEAD..."origin/<remote-ref>"
   ```

   Report the local-only and remote-only commits and ask whether to merge, rebase, or use the remote branch as authoritative.

6. Before handoff, verify all of the following:

   ```bash
   git -C <target-path> config --get "branch.<local-ref>.remote"  # must be origin
   git -C <target-path> config --get "branch.<local-ref>.merge"   # must be refs/heads/<remote-ref>
   git -C <target-path> pull --ff-only
   git -C <target-path> push --dry-run
   ```

   If the repository has submodules, also run `git -C <target-path> submodule sync --recursive`, `git -C <target-path> submodule update --init --recursive`, and a final `git -C <target-path> status --short` when the requested checkout includes submodule code.

## Workflow

For Wukong `rum-wrap` / `common-rum-wrap` checkout, comparison, or migration, first read the Git layout version boundary in `references/rum-mapping.md`.

1. Classify the request:
   - **List RUM inventory**: read `references/rum-mapping.md`, then use `scripts/releasego_rum_inventory.py` when stable markdown/json output is useful. Use `--kind dependencies` for shared internal packages (二方包).
   - **Modify an internal dependency**: read the shared dependency mapping in `references/rum-mapping.md`. Wukong and Guanyun use the same `app-dc-common` repository; fetch its source only when the requested change requires modifying the package, resolving the appropriate ref from the consuming application's dependency version or the user's request.
   - **Extract changes**: read `references/releasego-workflow.md`, then use ReleaseGo data plus `scripts/releasego_git_compare.py`.
   - **Migrate code**: read `references/output-contract.md`, confirm the target local repo/branch, then follow `references/releasego-workflow.md` migration strategy.
   - **Build app in Jenkins**: read `references/jenkins-build.md`, submit builds quickly, monitor by API, and capture Build ID.
   - **Fill ReleaseGo after build**: read `references/releasego-fill-after-build.md`, verify `等待集成`, then use `参与发版`, `变更应用`, and `变更配置`.
   - **App/config mapping**: read `references/rum-mapping.md`.
2. Resolve the release using API-first extraction and auth recovery once if needed.
3. Resolve selected app/config display name, git repository URL, release ref, and base ref. Before using a worktree for migration, follow **Git Worktree Checkout Safety** and report its upstream/fast-forward verification.
4. Generate compare output with commits, changed files, stats, patch, and GitLab compare URL candidate when available.
5. For migration, prefer safe Git-native merge/cherry-pick with local traceability; use manual porting only when history/layout makes Git-native migration unsafe.
6. Report success or exact stop point using `references/output-contract.md`.

## Scripts

Use a real Python 3 interpreter. On Windows, set UTF-8 mode before validation/packaging when the shell default encoding is not UTF-8.

```bash
python <skill-root>/scripts/releasego_doctor.py
python <skill-root>/scripts/releasego_config.py --require-credentials --json
python <skill-root>/scripts/releasego_http_session.py login-test --probe-release-version <release-version>
python <skill-root>/scripts/releasego_http_session.py release-list --release-version <release-version> --summary
python <skill-root>/scripts/releasego_http_session.py config-list --release-version-id <release-id> --summary
python <skill-root>/scripts/releasego_http_session.py apps-by-product --product-code app --summary
python <skill-root>/scripts/releasego_http_session.py application-versions --application-id com.tingyun.app:app-api --summary
python <skill-root>/scripts/releasego_git_tag.py --repo-url git@git.tingyun.com:app3/app-api.git --tag-name <tag-name> --ref master --verify-only
python <skill-root>/scripts/releasego_gitlab_session.py login-test
python <skill-root>/scripts/releasego_gitlab_session.py project-search --query rum-wrap
python <skill-root>/scripts/releasego_gitlab_session.py compare --project o11y-rum/rum-wrap --from-ref feature/2.2.0 --to-ref feature/2.3.0-dameng
python <skill-root>/scripts/releasego_gitlab_session.py branches --project o11y-rum/rum-wrap --search feature/2.3.0
python <skill-root>/scripts/releasego_jenkins_session.py auth-test
python <skill-root>/scripts/releasego_jenkins_session.py job-parameters --job-url https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/app/job/app-api/
python <skill-root>/scripts/releasego_jenkins_session.py queue
python <skill-root>/scripts/releasego_jenkins_session.py trigger-build --job-url https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/app/job/app-api/ --tag <tag> --confirm-trigger yes
python <skill-root>/scripts/releasego_rum_inventory.py --line 3.0 --kind apps --format markdown
python <skill-root>/scripts/releasego_rum_inventory.py --line 4.0 --kind dependencies --format markdown
python <skill-root>/scripts/check_text_integrity.py <skill-root>
```

PowerShell equivalent:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
python <skill-root>/scripts/releasego_doctor.py
```

## Packaging Safety

Before packaging, run:

```bash
python <skill-root>/scripts/check_text_integrity.py <skill-root>
```

This must fail if `<skill-root>/config.local.json` or a Python `__pycache__` directory exists. When the installed directory contains local configuration or caches, copy only public source files to a clean staging directory named `releasego`, then validate and package the staging copy. Preserve the user's local configuration; do not delete it to make packaging pass. The shared `.skill` package must contain `config.example.json`, but must never contain `config.local.json`, `__pycache__`, or `.pyc` files. Inspect the resulting archive and compare it with the public source files.

Run offline regression tests before packaging changed helpers:

```bash
python -B -m unittest discover -s "<skill-root>/tests" -v
```

These tests use synthetic credentials and mocked HTTP transport. Windows tests and simulated Darwin path checks do not substitute for native macOS validation.

## References

- `references/releasego-workflow.md`: ReleaseGo/GitLab extraction procedure, API-first strategy, and UI fallback rules.
- `references/jenkins-build.md`: Jenkins job mapping, parameterized build flow, API monitoring, and handoff to ReleaseGo app changes.
- `references/releasego-fill-after-build.md`: after-build ReleaseGo filling workflow for DEV participation, app changes, and config changes.
- `references/rum-mapping.md`: known 3.0/4.0 RUM app/config/shared dependency repositories and Jenkins mapping, including when to fetch dependency source.
- `references/output-contract.md`: required compare, migration, Jenkins, ReleaseGo fill, and failure templates.
