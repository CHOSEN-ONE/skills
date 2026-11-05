# Jenkins Build

Use this workflow when a RUM application has been tagged and must be built in Jenkins before filling the corresponding ReleaseGo application row.

## Scope And Required Inputs

This workflow currently covers only verified 3.0 / 悟空 RUM application jobs. Do not guess 4.0 / 观云 Jenkins jobs; ask the user for the job URL when needed.

Required inputs:

- application name;
- git tag to build;
- ReleaseGo release version to fill after the build succeeds.

Schema/config changes do not need Jenkins builds. For schema/config changes, tag the config repository and use `references/releasego-fill-after-build.md` for `变更配置`.

## Login

Require a verified HTTPS endpoint. Every job/build URL and redirect must have the same origin as `jenkinsBaseUrl`; do not attach credentials to an unrelated URL or bypass this check. TLS failure is a stop point, not a reason to downgrade or disable verification.

1. Prefer browserless Jenkins API access with `scripts/releasego_jenkins_session.py`.
2. Use LDAP Basic Auth for JSON/log endpoints. Validate with `GET /whoAmI/api/json`; success has `authenticated: true` and `anonymous: false`.
3. Use the browser only for UI fallback, MFA/captcha/account-selection flows, new interface discovery, or a real build-submission test explicitly authorized by the user.
4. If Jenkins redirects to `https://jenkins-new.tingyun.com/login?...` or returns login HTML for an API call, retry once with Basic Auth before falling back to browser login.
5. Stop and ask the user if Basic Auth fails, MFA/captcha appears, Jenkins requires an account-selection decision, or the retry is still unauthenticated.

Keep passwords only in the private local configuration described in `SKILL.md` or environment variables. Never copy cookies from the user's normal Chrome or write session cookies, auth dumps or logs into the shared skill. Exclude private configuration from packages. Redact usernames, passwords and tokens from output, including parameter `name`/`value` pairs and complete log text before truncating it.

## 3.0 RUM Jenkins Jobs

| Application | Jenkins job |
| --- | --- |
| common-js-config | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/common/job/common-js-config/` |
| app-dc-frontend | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/app/job/app-dc-frontend/` |
| mp-api | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/mp/job/mp-api/` |
| browser-api | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/browser/job/browser-api/` |
| app-deobfuscator-dubbo | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/app/job/app-deobfuscator-dubbo/` |
| app-api | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/app/job/app-api/` |
| common-rum-wrap | `https://jenkins-new.tingyun.com/view/3.6.x-releasego/job/common/job/common-rum-wrap/` |

## Build With Parameters

Prefer API for status discovery and verification. A browserless POST trigger candidate is known, but it queues a real build and must not be tested or used unless the user explicitly authorizes the build submission.

1. Resolve the mapped Jenkins job for the exact application.
2. Before triggering, read the job JSON API and record `nextBuildNumber` and `lastBuild`.
3. Read parameter definitions from the job API and identify the tag parameter.
4. Fill the tag parameter with the requested git tag.
   - Prefer the parameter whose label/name is exactly or obviously `tag`.
   - If multiple tag-like parameters exist and the correct one is unclear, stop and ask the user.
5. Start the build only after explicit user authorization for that build.
6. Use the job JSON API to confirm the new build number appears.
7. Use the build JSON API to verify the `TAG` parameter equals the requested tag.

Builds normally take several minutes to more than ten minutes. Poll or refresh the build page until the build completes.

## Multiple Application Builds

When one request needs builds for multiple applications, do not build them serially.

Use this fan-out/fan-in pattern:

1. If a ReleaseGo release version is provided for post-build filling, verify the release exists and is `等待集成` before triggering builds.
2. Resolve every application to its Jenkins job URL and requested tag.
3. Compute all required ReleaseGo product lines and prepare `参与发版` once for the whole batch before application rows are filled. This can be done before triggering builds or while builds are queued/running.
4. Submit all requested Jenkins builds as quickly as practical, one app/job at a time, without waiting for earlier builds to finish.
5. Do not try to manage Jenkins executor concurrency limits in this skill. If Jenkins allows only a few concurrent builds, let the extra builds stay in the Jenkins queue.
6. For each submitted build, record:
   - application name;
   - job URL;
   - requested tag;
   - expected/new build number when available;
   - build URL when available.
7. Monitor all submitted builds independently through the APIs below.
8. As soon as a single application's build reaches `SUCCESS`, fill that application's ReleaseGo row immediately if the ReleaseGo release version and product-line participation prerequisites are ready.
9. Continue monitoring/filling the remaining applications. A failure in one application should not stop already-running successful applications from being filled, but report the failed application clearly.

Practical trigger rule: it is acceptable for the UI clicks/submissions to happen one after another, but do not wait for any build result before submitting the next application build.

## API-First Monitoring

Validated Jenkins API endpoints:

- Auth test with Basic Auth:
  ```text
  GET /whoAmI/api/json
  ```
- Job parameter definitions:
  ```text
  GET <jobUrl>/api/json?tree=nextBuildNumber,property[parameterDefinitions[name,type,description,defaultParameterValue[value]]],actions[parameterDefinitions[name,type,description,defaultParameterValue[value]]]
  ```
  Verified on 2026-07-11 for `app-api`: parameters are `TAG` (`PT_TAG`) and `sonar.skip` (`BooleanParameterDefinition`).

- Job status:
  ```text
  GET <jobUrl>/api/json?tree=nextBuildNumber,lastBuild[number,result,building,url,timestamp,duration],builds[number,result,building,url,timestamp,duration]{0,8}
  ```
- Build status and parameters:
  ```text
  GET <buildUrl>/api/json?tree=number,url,building,result,duration,estimatedDuration,timestamp,actions[parameters[name,value]],executor[currentExecutable[number,url]]
  ```
- Progressive console log:
  ```text
  GET <buildUrl>/logText/progressiveText?start=<offset>
  ```
- Queue list:
  ```text
  GET /queue/api/json
  ```
- Queue item:
  ```text
  GET /queue/item/<queueId>/api/json
  ```
- Executor/computer summary:
  ```text
  GET /computer/api/json
  ```
- Build trigger candidate:
  ```text
  POST <jobUrl>/buildWithParameters
  ```
  Form fields include `TAG=<git tag>` and optional `sonar.skip=true|false` when that parameter exists. Use `scripts/releasego_jenkins_session.py trigger-build ... --confirm-trigger yes` only after the user explicitly approves the build.

Use response headers from `progressiveText`:

- `X-More-Data: true` means the build/log is still streaming.
- `X-Text-Size` is the next `start` offset for incremental polling.

Observed note: `GET https://jenkins-new.tingyun.com/crumbIssuer/api/json` returned `404` on 2026-06-26 and again with Basic Auth on 2026-07-11. Do not assume Jenkins crumb API is available.

For a submitted job, use the queue item ID to resolve the build number and verify the build status before proceeding.

## Build Result

Treat the build as successful only when Jenkins completes without an error/failure/abort indication. Prefer explicit Jenkins success state when visible.

API success criteria:

- build JSON has `building: false`;
- build JSON has `result: "SUCCESS"`;
- build JSON `actions[].parameters` includes `TAG = <requested tag>`;
- progressive log has no more data and ends with `Finished: SUCCESS` when log access is available.

On success:

1. Capture the build number as ReleaseGo `Build ID`.
2. Capture the build URL and git tag.
3. Capture package/image metadata from the progressive log when available, such as `buildCommitId`, `imageId`, `packageRepoPath`, and `packageName`.
4. Query ReleaseGo build metadata after Jenkins success when application IDs or same-name artifacts are ambiguous:
   - `GET /view/application/getApplicationVersionListByApplicationId?applicationId=<applicationId>`
   - `GET /view/application/getApplicationBuildIdListByApplicationId?buildId=<applicationVersionId>`
   Match both `buildNumber` and `buildTag` before filling ReleaseGo.
5. Continue to `references/releasego-fill-after-build.md` and perform `参与发版` and `变更应用` for the same ReleaseGo release/application when the user has provided the ReleaseGo release version.

On failure or uncertainty:

1. Do not edit ReleaseGo application rows.
2. Report the failed/uncertain Jenkins build URL, application, tag, and visible error state.
3. Ask for user direction before retrying or filling ReleaseGo.

## Stop Points

Stop with a specific reason when:

- Jenkins login is not ready;
- login recovery retried once but the target Jenkins page/API is still unauthenticated;
- application name is missing;
- git tag is missing;
- ReleaseGo release version is missing for the post-build fill;
- the application has no verified Jenkins job mapping;
- the tag parameter cannot be identified safely;
- the build fails, aborts, or times out;
- the build completes but Build ID/build number cannot be identified;
- ReleaseGo fill prerequisites are missing after Jenkins succeeds.
