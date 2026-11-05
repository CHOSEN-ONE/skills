# Output Contract

## Compare Success

Report at least:

```markdown
# ReleaseGo Compare: <release> / <app-or-config>

Status: success
Release: <requested release>
Base release: <base release>
Item: <ReleaseGo item name>
Repository: <git url>
Base ref: <base ref>
Head ref: <release ref>
GitLab compare: <verified/candidate/unavailable>
Output directory: <path>

## Summary
- Commits: <count>
- Changed files: <count>
- Patch: <path>

## Commits
<oldest to newest commit list>

## Files
<name-status list or path to files.txt>
```

## Compare Failure

Report:

```markdown
Status: failed
Stop point: <specific stop point>
Release: <release if known>
Item: <item if known>
Details: <short actionable reason>
Next required input/action: <what is needed>
```

## Migration Success

Report at least:

```markdown
# ReleaseGo Migration: <target repo>

Status: success
Target repo: <path>
Target branch: <branch>
Source repo: <git url or patch file>
Applied by: merge commit | cherry-pick commit | git apply --3way | manual port
Commits/patch: <list>
Auto commit: yes for Git-native merge/cherry-pick | no for manual port

## Working Tree
<git status --short>

## Verification
<commands run or commands still required>
```

## Migration Failure

Report:

```markdown
Status: failed
Stop point: <dirty worktree | branch mismatch | fetch failed | unknown commit | conflict | patch failed>
Target repo: <path>
Target branch: <expected/current>
Details: <short actionable reason>
Recovery: <exact command or manual action>
```

## Jenkins Build Success

Report at least:

```markdown
# Jenkins Build: <application>

Status: success
Application: <ReleaseGo app name>
Jenkins job: <job url>
Git tag: <tag>
Build ID: <build number>
Build URL: <build url>
Duration: <observed duration if known>
Verified by: job API | build API | progressive log
Build parameters: TAG=<tag>
Package/image metadata: <packageName/imageId/buildCommitId if available>
Next action: fill ReleaseGo application change for <release version>
```

## Jenkins Build Failure

Report:

```markdown
Status: failed
Stop point: <jenkins login not ready | unknown app job | tag parameter missing | build failed | build aborted | build timed out | build id missing>
Application: <app if known>
Jenkins job: <job url if known>
Git tag: <tag if known>
Details: <short actionable reason>
Next required input/action: <what is needed>
```

## Jenkins Batch Build Progress

Report batch progress with independent application statuses:

```markdown
# Jenkins Batch Build

Status: in_progress | partial_success | success | failed
Release version: <ReleaseGo version if provided>

| Application | Job | Tag | Build ID | Build status | ReleaseGo fill status |
| --- | --- | --- | --- | --- | --- |
| <app> | <job url> | <tag> | <build number or queued> | queued/building/SUCCESS/FAILURE/ABORTED | pending/filled/skipped/failed |

Rule: builds are submitted without waiting for earlier builds to finish; Jenkins queue/concurrency limits are left to Jenkins.
```

## ReleaseGo Fill Success

Report at least:

```markdown
# ReleaseGo Fill: <release version>

Status: success
Release version: <version>
Release id: <id>
Release status before edit: 等待集成

## Participation
- Already present: <product lines>
- Added: <product lines>
- Resolve and report the catalog code separately from its display name; verified participation is an exact-code row in the target release, not merely a successful save response.

## Applications
| Application | Product line | Git tag | Build ID | Verification |
| --- | --- | --- | --- | --- |
| <app> | <line> | <tag> | <build id> | <verified by UI/API> |

## Configs
| gitId | gitTag | Verification |
| --- | --- | --- |
| <gitId> | <tag> | <verified by UI/API> |
```

## ReleaseGo Fill Failure

Report:

```markdown
Status: failed
Stop point: <missing release version | release not waiting integration | missing tag/build id | product line unknown | app row missing | config row missing | save failed | verification failed>
Release version: <version if known>
Release id: <id if known>
Details: <short actionable reason>
Next required input/action: <what is needed>
```

## Defaults

- For approved migration, create local commits for Git-native merge/cherry-pick paths after conflicts are resolved and verification is run.
- Keep manually ported code staged/uncommitted for user review unless the user explicitly asks for a commit.
- Do not push.
- Do not silently switch branches.
- Do not ignore dirty worktrees unless the user explicitly allowed it.
- Keep generated reports under `<workspace>/.releasego/`.
