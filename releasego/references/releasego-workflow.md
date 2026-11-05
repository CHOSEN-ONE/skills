# ReleaseGo Workflow

## Entry Points

- ReleaseGo: `https://releasego.tingyun.com`
- GitLab default: `https://git.tingyun.com/`. For an authorized HTTP-only deployment, configure its HTTP base URL and explicitly enable `gitlabAllowHttp` as described in `SKILL.md`.
- For ReleaseGo JSON API tasks, use `scripts/releasego_http_session.py` first; it logs in with local credentials and keeps cookies in memory.
- For GitLab JSON API tasks, use `scripts/releasego_gitlab_session.py` first; it logs in through the GitLab LDAP callback and keeps cookies in memory.
- Apply the shared `ai-browser` baseline only when browser interaction, UI fallback, or new interface discovery is required. Use the configured AI browser CDP endpoint, defaulting to `http://127.0.0.1:9222`.
- Assume ReleaseGo and GitLab are already logged in. Open the target page or call the target API first.
- If either system redirects to a login page, wait a few seconds for browser autofill; if autofill is unavailable, load credentials from `scripts/releasego_config.py`. If account and password are populated, click `立即登录` and continue.
- After login, retry the original page/API action once.

All session requests and redirects must stay on their exact configured origin. HTTPS uses certificate verification. GitLab alone supports explicitly authorized HTTP through `gitlabAllowHttp`; simply configuring an HTTP URL is not enough. HTTP exposes login/session data in transit. Never downgrade automatically after a TLS failure or bypass the configured policy using the browser. Use each session's redactor for output and errors; never print raw response bodies or config/session objects containing credentials. Historical HTTP links do not themselves authorize a login; consult the current task authorization and local configuration. SSH repository operations can be used alongside the HTTP API.

## Release Concepts

- `3.0` is also called `悟空`.
- `4.0` is also called `观云`.
- `分叉 = 通用` can mean common 3.0/4.0 releases. Customer-specific forks are usually shown with the customer Chinese name.
- `版本号` is the concrete release identifier. 3.0 versions are usually `3.x`; 4.0 versions are usually `1.x` or `2.x`.
- Customer packages often include customer and request date, for example `V2.4.1-CustomerExample-20260622`.
- `基于版本` identifies the base release. Unchanged apps/configs should be compared against the corresponding item in that base release.
- This skill focuses on releases whose status is `已发布` / `已经发布`.

## API-First Extraction

1. Open the target ReleaseGo page or call the target ReleaseGo API directly.
2. Search or filter the release list by the user-provided release number.
3. Prefer authenticated same-origin API responses over manual UI scraping:
   - inspect XHR/fetch URLs visible from the browser session;
   - use the authenticated page context to call candidate JSON endpoints;
   - verify that response fields match visible list/detail fields before relying on them.
4. Do not hardcode unverified endpoint names. If an endpoint is discovered during a task, record it in that task's report. Update this skill only after the endpoint has worked repeatedly.
5. If an API response is unauthenticated, run login recovery once and retry the same API request. Treat `401`, `403`, redirects to login, login HTML instead of JSON, or a browser page sitting on a login URL as unauthenticated.
6. If API extraction is unstable after auth recovery, use the UI fallback below.

Validated API flows for ReleaseGo editing tasks:

- Browserless login: `POST /doLogin`
  - Body JSON fields: `username`, `password`
  - Expected success response: `{ "code": 200, "msg": "OK" }`
  - Validated with environment credentials on 2026-07-11; a subsequent release list query succeeded without browser state.
- Release list lookup: `GET /view/release/getReleaseList?page=1&limit=100&releaseVersion=<version>&status=&releaseForkName=`
- Config list lookup: `GET /view/release/getReleaseConfigList?releaseVersionId=<id>&page=1&limit=200`
- Config save/update: `POST /view/release/SaveOrUpdateReleaseConfig`
  - Body JSON fields: `id`, `gitId`, `gitTag`, `releaseVersionId`
  - Expected success response: `{ "code": 200, "msg": "OK" }`
  - Helper command: `releasego_http_session.py save-config ... --confirm-write yes`
- Post-save verification: re-read the config list endpoint above and confirm the target row's `gitTag` changed.

Validated API flows for ReleaseGo post-build application filling:

- Release plan lookup: `GET /view/plan/getPlanList?releaseVersionId=<id>&page=1&limit=200`
- Add product-line participation: `POST /view/plan/savePlan`
  - Body JSON fields: `releaseVersionId`, `product`; `product` is the exact `code` returned by `/getProductList`, never its display `name`.
  - Expected response: `{ "code": 200, "msg": "OK" }`; success additionally requires a unique exact-code plan row on read-back. An empty list or `already participating` response without that row is inconsistent state, not success.
  - Helper command: `releasego_http_session.py add-plan ... --confirm-write yes`
- Confirm newly added product-line update: `POST /view/plan/updateProductStatus`
  - Body JSON fields: `id` (the plan row id from a refreshed plan list)
  - Expected success response: `{ "code": 200, "msg": "OK" }`
  - Helper command: `releasego_http_session.py confirm-plan ... --confirm-write yes`
  - Verified on 2026-06-26: confirming a newly added `app` row changed `productCheck` from `0` to `1` and populated `productCheckUser`.
  - Apply only to product lines added in the current run; do not confirm unrelated existing plan rows.
- Product list lookup: `GET /view/application/getProductList`
  - Resolve all product lines dynamically from `code`/`name`; do not lowercase or infer a code from display text. Follow the safe replacement workflow in `releasego-fill-after-build.md` before deleting an application row.
- Application definitions by product: `GET /view/application/getApplicationListByProduct?productCode=<code>`
- Application versions: `GET /view/application/getApplicationVersionListByApplicationId?applicationId=<applicationId>`
- Build IDs for an application version: `GET /view/application/getApplicationBuildIdListByApplicationId?buildId=<applicationVersionId>`
  - The `buildId` query parameter is the full `applicationVersionId`.
- Application save/update: `POST /view/application/saveOrUpdateReleaseApplications`
  - Body JSON fields: `releaseVersionId`, `id` (optional), `productCode`, `applicationId`, `applicationVersionId`, `buildNumber`
  - Expected success response: `{ "code": 200, "msg": "OK" }`
  - Helper command: `releasego_http_session.py save-app ... --confirm-write yes`
- Application delete: `POST /view/application/delReleaseApplication`
  - Body JSON fields: `id`, `releaseVersionId`
  - Expected success response: `{ "code": 200, "msg": "OK" }`
  - Helper command: `releasego_http_session.py delete-app ... --confirm-write yes`

Resolve the release ID and base version ID before listing configuration, applications and plans. Match application versions and builds through their lookup endpoints.

Validated observations from 2026-06-23 and 2026-06-26:

- Release list JSON: `/view/release/getReleaseList?page=1&limit=100&releaseVersion=&status=&releaseForkName=`
- Release detail HTML: `/view/release/getReleaseDetail?releaseVersionId=<id>`
- Application list HTML: `/view/application/list?releaseVersionId=<id>`
- Application list JSON: `/view/application/getApplicationList?releaseVersionId=<id>&page=1&limit=100`
- Plan list HTML: `/view/plan/list?releaseVersionId=<id>`
- Plan list JSON: `/view/plan/getPlanList?releaseVersionId=<id>&page=1&limit=200`
- Plan save JSON: `/view/plan/savePlan`
- Plan product update confirm JSON: `/view/plan/updateProductStatus`
- Plan product update confirm result: refreshed plan rows show `productCheck = 1` and may include `productCheckUser`.
- Config list HTML: `/view/release/config/list?releaseVersionId=<id>`
- Config list JSON: `/view/release/getReleaseConfigList?releaseVersionId=<id>&page=1&limit=100`
- Config save/update JSON: `/view/release/SaveOrUpdateReleaseConfig`
- Release list fields include `id`, `forkName`, `releaseVersion`, `baseVersion`, `baseVersionId`, `parentVersion`, `ownerId`, `status`, `ctime`, and `releaseTime`.
- Observed status mapping: `4 = 已经发布`, `1 = 已经集成`, `0 = 等待集成`.
- Application JSON fields include `artifact`, `applicationId`, `version`, `scmTag`, `buildPackageRepoPath`, `buildPackageName`, `buildNumber`, `productName`, `sinceReleaseVersionId`, and `releaseApplicationsId`.
- Plan JSON fields include `id`, `releaseVersionId`, `product`, `productName`, `productCheck`, `productCheckUser`, and `tested`.
- Config JSON fields include `gitId`, `gitTag`, and `assemblyConfig`; `assemblyConfig` can include `gitGroup`, `gitProject`, `gitPath`, and `gitUrl`.

## UI Fallback

1. In the release list, locate the requested version and verify status.
2. Capture these list fields: `分叉`, `版本号`, `基于版本`, `状态`, and release detail link/button.
3. Click `查看` for the requested version.
4. In details, capture:
   - `配置信息`: database initialization SQL/config, nacos config, ClickHouse schema/proto, ES-related content.
   - `全量列表`: all apps in the release.
5. Interpret colors in `全量列表`:
   - red means changed in this release;
   - brown/yellow means changed in a historical base version;
   - no highlight usually means inherited without change.
6. Open the base release from `基于版本` and capture the same selected apps/configs there.

## Resolving Git Compare Inputs

For each requested app/config:

1. Normalize aliases with `references/rum-mapping.md`.
2. Prefer a repository URL shown by ReleaseGo. If none is shown, use the mapping file.
3. Extract the release ref for the selected item from the requested release detail.
4. Extract the base ref for the same item from the base release detail.
5. If either ref is missing, stop for that item and report the exact missing field.
6. Run `scripts/releasego_git_compare.py` with `--repo-url`, `--base`, `--head`, and an app-specific output directory.

For ReleaseGo config edits, prefer API over UI when the page exposes the current row id:

1. Fetch the release row with `/view/release/getReleaseList`.
2. Fetch the config rows with `/view/release/getReleaseConfigList`.
3. POST the changed row to `/view/release/SaveOrUpdateReleaseConfig`.
4. Re-fetch the config list and verify `gitTag` matches the requested value.
5. If any API call returns an unauthenticated signal, recover login once and retry the original API call before falling back to UI.

## Migration Strategy

For Wukong `common-rum-wrap`, read the Git layout version boundary in `rum-mapping.md` before choosing a migration strategy for `app-dc-wrap`, `browser-wrap`, or `mp-wrap`.

When the user approves migration, preserve Git traceability while keeping the scope clean:

1. Inspect the approved source commits/range and the target branch before applying changes.
2. Prefer merge only when the source ref/range contains exactly the approved migration scope and will not bring unrelated commits or files into the target branch. After conflicts are resolved and verification is run, create a local merge commit; do not push.
3. If merge would include unrelated content, or if the approved scope is an explicit commit subset, cherry-pick the selected commits. Prefer preserving the original commit messages, and use `-x` when useful for source-commit traceability; do not push.
4. If cherry-pick conflicts, resolve conflicts semantically against the target branch, then continue the cherry-pick so a local commit is created.
5. Use patch application or manual code porting only when merge and cherry-pick are inappropriate, such as incompatible repository history, moved modules, or submodule-to-subtree layout changes.
6. When manual porting is necessary, state why Git-native migration is unsafe and keep the manually ported code staged/uncommitted for user review unless the user explicitly asks for a commit.

## GitLab Compare

Prefer `scripts/releasego_gitlab_session.py` for GitLab API operations.

Validated browserless GitLab flow on 2026-07-11:

- Sign-in page: `GET /users/sign_in`
  - Parse hidden form field `authenticity_token`.
- LDAP login: `POST /users/auth/ldapmain/callback`
  - Form fields: `authenticity_token`, `username`, `password`, `remember_me=0`.
  - Verify login with `GET /api/v4/user`, expecting HTTP 200 JSON.
  - Do not parallelize multiple fresh GitLab login attempts unnecessarily; a single session should be reused for a batch of API calls.
- Project search: `GET /api/v4/projects?search=<query>&simple=true&per_page=<n>`
- Project detail: `GET /api/v4/projects/<urlencoded namespace/project>`
- Repository compare: `GET /api/v4/projects/<urlencoded namespace/project>/repository/compare?from=<base>&to=<head>`
- Branch list: `GET /api/v4/projects/<urlencoded namespace/project>/repository/branches?search=<query>&per_page=<n>`
- Tag list: `GET /api/v4/projects/<urlencoded namespace/project>/repository/tags?search=<query>&per_page=<n>`
- Commit list: `GET /api/v4/projects/<urlencoded namespace/project>/repository/commits?ref_name=<ref>&per_page=<n>`
- Commit diff: `GET /api/v4/projects/<urlencoded namespace/project>/repository/commits/<sha>/diff?per_page=<n>`
- Tag creation API candidate: `POST /api/v4/projects/<urlencoded namespace/project>/repository/tags`
  - Form fields: `tag_name`, `ref`, optional `message`.
  - On 2026-07-11, this returned `404 Project Not Found` for `app3/app-api` even when `GET /api/v4/projects/app3%2Fapp-api` succeeded in the same session. Do not rely on this API for tag creation on this GitLab instance.
- Git protocol tag creation:
  - Helper command: `releasego_git_tag.py --repo-url <repo> --tag-name <tag> --ref <branch-or-sha> --confirm-write yes`.
  - The helper creates a temporary repository under `.releasego/git-tag-work`, fetches the source ref, creates a lightweight tag, pushes `refs/tags/<tag>`, and verifies it with `git ls-remote`.

Verified examples:

- `project-search --query rum-wrap` returned `o11y-rum/rum-wrap` and `app3/rum-wrap`.
- `compare --project o11y-rum/rum-wrap --from-ref feature/2.2.0 --to-ref feature/2.3.0-dameng` returned HTTP 200 with `commitCount=111`, `diffCount=456`, and `compare_timeout=false`.
- `branches --project o11y-rum/rum-wrap --search feature/2.3.0` returned `feature/2.3.0-dameng`.
- `commits --project o11y-rum/rum-wrap --ref feature/2.3.0-dameng` returned commit rows with `id`, `short_id`, `title`, and `web_url`.
- `commit-diff --project o11y-rum/rum-wrap --sha 6efcac5d...` returned file-level diffs.
- Before a tag write, use the Git tag helper with the requested repo, ref and tag, and verify the resolved commit.

When the repository URL is under `git.tingyun.com`, construct a candidate compare URL in this shape:

```text
http://git.tingyun.com/<namespace>/<repo>/-/compare/<base>...<head>
```

Use local git output as the source of truth. Treat the URL as a convenience link until it is opened and verified in the authenticated GitLab session.

Validated observation from 2026-06-23:

- `http://git.tingyun.com/o11y-rum/rum-wrap` opens in the authenticated AI browser session.
- GitLab compare works with branch slashes URL-encoded, for example `feature%2F2.2.0...feature%2F2.3.0-dameng`.
- A valid compare page title follows this shape: `<base> to <head> · <group> / <project> · GitLab`.

## Failure Stop Points

Use specific stop points:

- ReleaseGo login not ready.
- Login recovery retried once but the target page/API is still unauthenticated.
- Release not found.
- Release status is not `已发布`.
- Base release not found.
- App/config not present in requested release.
- App/config not present in base release.
- Repository URL unknown.
- Git ref missing.
- Git fetch failed.
- Compare generated locally but GitLab URL not verified.
