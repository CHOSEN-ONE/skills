# Common Chandao API Pitfalls

## Browser Boundary

- Routine Chandao operations are HTTP-only. A user-requested endpoint/DOM discovery may use the AI-only browser via `ai-browser`, but never the user's normal Chrome and never UI-based effort writes.
- Cookies belong only in `<workspace>/.chandao-session/chandao-http-cookies.txt`. Delete the workspace session file if a fresh HTTP login is required.

## Authentication Responses

- An expired session can return JavaScript such as `self.location='/pro/user-login-...html'` instead of a login form. Treat it as unauthenticated and retry the original endpoint once after API login.
- `self.location='/pro/my-changepassword.html'` is not an authenticated result. Stop and ask the user to update the password and environment variable; never automate that account change.
- Do not parse a login redirect as an empty Bug, task, or effort list.
- Do not send an empty or fixed `passwordStrength` field. Compute it with the instance's `computePasswordStrength()` algorithm; an empty value can produce a false password-change redirect for a valid account.

## HTTP And Write Safety

- Use the documented endpoint and field names from `chandao-api.md`; do not create guessed `/zentao/...` routes.
- Use `my-tasks` to list tasks, `task --id <ID>` to inspect one task, and `effort --id <ID>` to inspect one effort. An `invalid choice: 'task'` error means the installed client is stale or the command was misspelled; do not treat it as a server outage.
- `--apply` is mandatory for create, edit, and delete. It confirms the command itself but does not replace the user's authorization for a real write.
- Check for duplicate date/hours/content before creating a log. The server can reject repeated task/date/work text even when consumed differs, so split entries need distinct, truthful phase descriptions. After a successful create, find and re-read the new record rather than retrying the same payload.
- A response can contain `created=true` and an effort ID before a later retry is rejected as a duplicate. Preserve that ID, re-read it, and rescan the date before deciding whether anything is missing.
- On Windows PowerShell, use `curl.exe` for manual endpoint diagnostics. Older PowerShell versions do not support `Invoke-WebRequest -SkipHttpErrorCheck`.

## Text And Parsing

- Keep Python source and validation output UTF-8. Run with `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` when the local default is not UTF-8. When a native subprocess is parsed from Python, set the environment override on the child and decode captured bytes explicitly; do not trust garbled PowerShell display text.
- Parse Bug/task/effort IDs from their stable view links rather than fragile screen coordinates or table columns.
- If the server form fields no longer match the documented create/edit contract, stop before POSTing and update the reference only after a read-only validation.
