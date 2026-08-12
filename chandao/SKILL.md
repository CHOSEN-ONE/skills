---
name: chandao
description: Use when querying, recording, verifying, repairing, or backfilling Tingyun Chandao (ZenTao) tasks, effort logs, assigned bugs, bug details, or API sessions without browser automation.
---

# Chandao API

Use the bundled HTTP client as the normal execution path. For explicit, read-only endpoint or DOM discovery, use the AI-only browser through `ai-browser`; never use a normal Chrome profile, copy browser cookies, or perform Chandao writes through the UI.

## Configuration

- Read `TINGYUN_USERNAME` and `TINGYUN_PASSWORD` from the environment. Never print either value.
- Store the HTTP cookie jar only at `<workspace>/.chandao-session/chandao-http-cookies.txt`; never write credentials, cookies, or API responses into this skill directory.
- Run commands from the user workspace. Use `python <skill-root>/scripts/chandao_api.py --workspace <workspace> ...`.
- If either variable is absent, login fails, MFA/captcha is required, or Chandao redirects to password change, stop and explain the required user action. Do not change passwords automatically.

## Session Rules

1. Call the target HTTP endpoint directly. A valid cookie proceeds without an extra login check.
2. If the response is a login page or a JavaScript redirect to `user-login-*`, fetch `verifyRand`, submit the documented double-MD5 login request, verify `my.html`, then retry the original request once.
3. If the second request is unauthenticated, stop. If Chandao redirects to `my-changepassword`, stop before parsing or writing.
4. API endpoints and contracts are in `references/chandao-api.md`. Do not invent unverified URLs.

For a user-requested read-only contract check, open the target page in the AI-only browser, record only the verified URL and field structure, then implement and test the HTTP client. Return to the API-only path for all routine queries and effort writes.

## Read Operations

All commands emit JSON and have no side effects.

```powershell
python scripts/chandao_api.py --workspace . auth-check
python scripts/chandao_api.py --workspace . my-bugs --scope assignedTo --limit 20
python scripts/chandao_api.py --workspace . bug --id 60515
python scripts/chandao_api.py --workspace . my-tasks --scope assignedTo --limit 20
python scripts/chandao_api.py --workspace . task --id 81742
python scripts/chandao_api.py --workspace . my-efforts --scope all
python scripts/chandao_api.py --workspace . calendar-efforts --year 2026
python scripts/chandao_api.py --workspace . effort --id 308704
```

- Use `my-tasks` for task lists and `task --id <ID>` for one task's read-only detail. Use `effort --id <ID>` for one effort.
- `my-bugs` defaults to `assignedTo`. Supported scopes: `assignedTo`, `openedBy`, `resolvedBy`, `closedBy`.
- `my-tasks` defaults to `assignedTo`. Supported scopes: `assignedTo`, `openedBy`, `finishedBy`, `closedBy`, `canceledBy`.
- `my-efforts` supports `all`, `thisweek`, `lastweek`, `thismonth`, and `lastmonth`. The all-scope page is paginated; use `calendar-efforts` for a year's complete event list.
- Bug detail output includes ID, title, product, status, severity, priority, and reproduction steps when exposed by the page.
- Task detail output includes ID, title, project, module, related story, assignee, type, status, progress, priority, estimate, consumed, remaining, start dates, and deadline when exposed by the page.

## Effort Writes

Write operations always require explicit user authorization and the command-level `--apply` flag. Never add `--apply` merely to test an endpoint.

```powershell
python scripts/chandao_api.py --workspace . create-effort --object-type task --object-id 81473 --date 2026-07-14 --consumed 4 --work "work content" --apply
python scripts/chandao_api.py --workspace . edit-effort --id 308704 --object-id 80299 --date 2026-07-14 --consumed 4 --left 999 --work "corrected content" --apply
python scripts/chandao_api.py --workspace . delete-effort --id 308704 --apply
```

- Never log future dates. The current date is allowed.
- A single log must be greater than `0` and at most `4` hours.
- Before creation, check for the same date, hours, and content. The server may also reject a second entry with the same task, date, and work text even when its consumed hours differ. If one work item must be split, use truthful stage-specific wording (for example, `需求梳理` and `问题验证`), never meaningless filler.
- If a create call reports a duplicate after returning an effort ID, or a retry follows a `created=true` response, stop retrying first and re-read the returned/existing ID. Treat the write as potentially successful until the calendar and effort detail prove otherwise.
- On Windows, set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` when capturing API JSON. Validate decoded JSON fields, not mojibake shown by a PowerShell console.
- After creation or edit, re-read the relevant record; a closed or success-looking response is not proof.
- For task logs, use `left=999` unless the user supplies a confirmed remaining-hours value.
- The task `recordEstimate` page and the `effort-createForObject-task` page use the same three-row form contract. Use the documented create command for each approved entry; it is browserless and verifies each result.
- Chandao also exposes a batch-create form. Its read contract is documented, but do not submit its raw array payload until a real write is explicitly authorized and the supplied entries have been reviewed.
- Repair a wrong task/object or corrupted text by deleting the confirmed bad entry first, then creating the corrected entry, then rechecking the task or Bug history. Do not stack a compensating log on top of the bad one.

Read `references/time-logging.md` before any effort write. It preserves the date, statutory-calendar, leave, task-selection, duplicate, and verification rules.

## Bug Resolution

Resolving a Bug is an HTTP-only write operation. It requires explicit user authorization and the command-level `--apply` flag; do not use a browser or add `--apply` only to probe the endpoint.

```powershell
python scripts/chandao_api.py --workspace . resolve-bug --id 60683 --apply
python scripts/chandao_api.py --workspace . resolve-bug --id 60686 --resolution fixed --resolved-build trunk --comment "Optional resolution note" --apply
```

- `--resolution` defaults to `fixed`; `--resolved-build` defaults to `trunk`.
- Before posting, the client reads the real resolve form and accepts only the solution and build values currently exposed by Chandao. It preserves the form's current `resolvedDate` and `assignedTo` values.
- Do not pass `--comment` when no comment is required. The client omits the field entirely; when a comment is supplied, it first confirms that the form exposes a comment field.
- A successful POST is not enough. The client re-reads the Bug detail and verifies `Bug状态`、`解决方案`、`解决版本` before reporting success.
- Refer to `references/chandao-api.md` for the verified form endpoint and fields.

## Safety And Output

- Treat Bug/task queries as read-only. Do not create, edit, assign, resolve, or close anything unless requested.
- Do not log passwords, cookie values, request bodies containing credentials, or full authenticated HTML responses.
- On an HTTP or parsing contract change, stop with the endpoint and safe diagnostic only. Record validated corrections in `references/chandao-api.md`.
- Before packaging, run the unit tests, `scripts/check_text_integrity.py`, and inspect the skill directory for session or cache files.

For API failure modes and Windows command notes, read `references/pitfalls.md`.
