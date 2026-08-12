# Chandao HTTP Contracts

Base URL: `https://chandao.tingyun.com/pro/`.

The instance is ZenTao Pro 9.0.3 and uses `PATH_INFO` routes. The Python client uses only the standard library and persists `zentaosid` in the workspace cookie jar.

## CLI Command Contract

The wrapper exposes these subcommands: `auth-check`, `my-bugs`, `bug`, `resolve-bug`, `my-tasks`, `task`, `my-efforts`, `calendar-efforts`, `effort`, `create-effort`, `edit-effort`, and `delete-effort`. Use `my-tasks` to list tasks, `task --id <ID>` to inspect one task, and `effort --id <ID>` to inspect one effort.

## Authentication

| Method | Endpoint | Contract |
| --- | --- | --- |
| `GET` | `user-login.html` | Parse hidden `verifyRand`. |
| `POST` | `user-login.json` | Send `account`, `password=md5(md5(plain)+verifyRand)`, computed `passwordStrength`, `referer=/pro/my.html`, `verifyRand`, `keepLogin=0`. A successful JSON response has `status: success`. |
| `GET` | `my.html?onlybody=yes` | Verify the new session. |

Unauthenticated requests may return either the login document or a tiny document with `self.location='/pro/user-login-...html'`. Both mean login once and retry the original endpoint once.

`self.location='/pro/my-changepassword.html...'` means the account must change its password. Stop without parsing the result or attempting a write. Do not automate password changes.

`passwordStrength` must match the `computePasswordStrength()` function loaded from the instance's `my.full.js`. Sending it empty can incorrectly route an otherwise valid login to the password-change page. The bundled client implements the observed algorithm; do not substitute a fixed number.

## Verified Read Endpoints

| Operation | Endpoint |
| --- | --- |
| Assigned Bugs | `my-bug-assignedTo.html?onlybody=yes` |
| Bug scopes and paging | `my-bug-{scope}-id_asc-0-{limit}-{page}.html?onlybody=yes` |
| Bug detail | `bug-view-{bugID}.html?onlybody=yes` |
| Assigned tasks | `my-task-assignedTo.html?onlybody=yes` |
| Task scopes and paging | `my-task-{scope}-id_asc-0-{limit}-{page}.html?onlybody=yes` |
| Task detail/history | `task-view-{taskID}.html?onlybody=yes` |
| My effort list | `my-effort.html?onlybody=yes` |
| My effort scopes | `my-effort-{all|thisweek|lastweek|thismonth|lastmonth}.html?onlybody=yes` |
| Effort detail | `effort-view-{effortID}.html?onlybody=yes` |
| Effort calendar page | `effort-calendar.html?onlybody=yes` |
| Effort calendar JSON | Read `effort-calendar` first, then call its exposed `effort-ajaxGetEfforts-{userID}-{year}.html?onlybody=yes` URL |

`my-bug-*` and `my-task-*` pages expose stable `bug-view-{id}` and `task-view-{id}` links. Parse those links rather than table column positions. The all-scope effort page exposes `effort-view-{id}-my.html`; its detail route is still `effort-view-{id}.html`.

The calendar JSON is the reliable full-year source for duplicate detection. Its event objects contain `id`, `title`, `start`, `end`, `url`, and `consumed`; re-read candidate effort detail pages before treating a title match as a duplicate.

The verified task detail page exposes `TASK#<id> <title> / <project> - ...` in the page title. Its basic-information table includes project, module, related story, assignee, type, status, progress, and priority; its effort table includes estimate, consumed, remaining, estimated start, actual start, and deadline. Detail sections expose task description, story description, and acceptance criteria. The `task --id <ID>` command returns these fields when present and uses `task-view-<ID>.html?onlybody=yes`.

The write API may treat identical task/date/work text as a duplicate even when the consumed hours differ. When splitting one activity into multiple entries, keep each description truthful and phase-specific. If a retry returns a duplicate error after an earlier response supplied an effort ID, re-read that ID before creating anything else.

## Bug Resolve Form

| Operation | Form endpoint | Request data |
| --- | --- | --- |
| Resolve Bug | `bug-resolve-{bugID}.html?onlybody=yes` | `status=resolved`, `resolution`, `resolvedBuild`, `resolvedDate`, `assignedTo`, optional `comment` |

`resolve-bug` is a browserless write operation and always requires both explicit user authorization and `--apply`. Read the form before the POST; use only its actual `resolution` and `resolvedBuild` option values. The client preserves the form's existing `resolvedDate` and selected `assignedTo` values instead of constructing them locally.

The documented defaults are `resolution=fixed` (已解决) and `resolvedBuild=trunk` (主干), but they are accepted only when the current form exposes those values. Do not submit `comment` unless the caller supplies one; if a supplied comment has no matching textarea in the form, stop without writing.

After a successful POST, re-read `bug-view-{bugID}.html?onlybody=yes` and verify all three values: `Bug状态=已解决`, `解决方案` equals the selected resolution label, and `解决版本` equals the selected build label. Treat an unverified response as failure and do not claim the Bug was resolved.

## Effort Forms

| Operation | Form endpoint | Request data |
| --- | --- | --- |
| Create for task or Bug | `effort-createForObject-{objectType}-{objectID}.html?onlybody=yes` | `id[1]`, `dates[1]`, `consumed[1]`, `left[1]`, `work[1]`, `objectType[1]`, `objectID[1]` |
| Task log alias | `task-recordEstimate-{taskID}.html?onlybody=yes` | Same three-row create form as `effort-createForObject-task-{taskID}` |
| Edit | `effort-edit-{effortID}.html?onlybody=yes` | `date`, `consumed`, `left`, `objectID`, `work` |
| Delete | `effort-delete-{effortID}.html?onlybody=yes` | `POST`, no body |
| Batch-create form | `effort-batchCreate-{YYYYMMDD}.html?onlybody=yes` | `date`, `id[]`, `work[]`, `objectType[]`, `project[]`, `left[n]`, `consumed[]`; read-validated only |

The create and edit GET forms were read-validated. Every POST is guarded by `--apply`, requires user authorization, and must be re-read after the request. Do not treat a hidden-frame response as success. The batch-create POST has not been issued during endpoint discovery; use repeated verified single-entry creates until a concrete batch write is authorized.

## Non-Endpoint Rules

- A task log needs an explicit target task. Do not infer a narrow customer task from a shared keyword.
- Queries may use the default assigned-to-me scopes. Broader scopes require the user to ask for them or a documented fallback.
- Request output must not include credentials, cookie values, raw login JSON, or raw authenticated HTML.
