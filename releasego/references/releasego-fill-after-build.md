# ReleaseGo Fill After Build

Use this workflow when code/schema changes have already been tagged and any required Jenkins builds are complete, and the user asks to fill a ReleaseGo release through the DEV operations. If an application still needs a Jenkins build, use `references/jenkins-build.md` first.

## Scope And Required Inputs

This workflow fills ReleaseGo after Jenkins is complete. For 3.0 RUM application builds, use `references/jenkins-build.md`; schema/config changes only need tags and do not need Jenkins builds.

Before editing ReleaseGo, require the user to provide the exact ReleaseGo release version to fill. Do not infer it from nearby releases.

Collect the requested changes:

- Application changes: application name, git tag from the Jenkins build tag, and Build ID from this Jenkins build.
- Config/schema changes: `gitId` and git tag. Schema/config changes require tags but do not require Jenkins Build ID.
- Version line: `3.0`/`悟空` or `4.0`/`观云`, when product-line inference is needed.

Stop before editing if any required tag, Build ID, application name, config `gitId`, or release version is missing.

## Status Gate

1. Prefer `scripts/releasego_http_session.py` and browserless ReleaseGo login for all JSON API work.
2. Resolve the exact release with the release list API first:
   `GET /view/release/getReleaseList?page=1&limit=100&releaseVersion=<version>&status=&releaseForkName=`
3. If the browserless API response is unauthenticated or unstable after one retry, use the configured AI browser as fallback.
4. Verify the matched row is exact and `status = 0`, which means `等待集成`.
5. If the release is not `等待集成`, stop. Do not fill releases that are `已经集成`, `已经发布`, deleted, or otherwise not waiting integration.

## DEV Entry

On the target release row, open the `DEV` operation. The relevant actions are:

- `参与发版`
- `变更应用`
- `变更配置`

Use `DEV`, not `OPS`, for this workflow.

## 参与发版

If application changes are requested, first ensure every required product line is participating in the release. ReleaseGo only allows application changes for participating product lines.

Resolve the exact product code for every application from the product directory and application metadata. This applies equally to 3.0, 4.0 and custom product lines.

`GET /view/application/getProductList` returns `code` and `name`. `GET /view/application/getApplicationListByProduct?productCode=<code>` identifies applications under that code. Submit `code` unchanged in both `savePlan.product` and application `productCode`; display fields `name` / `productName` are only for explanation and UI labels.

Examples of code/display-name pairs are `app`/`APP`, `mp`/`MP`, `browser`/`Browser`, `common`/`Common`. These are examples, not a fixed allowed set. A custom code may itself contain uppercase characters. Do not derive codes by lowercasing display names.

Repository mappings may suggest which product to look up, but the current API metadata is authoritative. If it is missing or ambiguous, resolve the application/product identity before a write; do not experiment with display names or spelling variants.

Procedure:

1. Prefer the plan APIs:
   - `GET /view/plan/getPlanList?releaseVersionId=<id>&page=1&limit=200`
   - `POST /view/plan/savePlan` with JSON body `releaseVersionId`, `product`
   - `POST /view/plan/updateProductStatus` with JSON body `id`
   - Helper commands: `releasego_http_session.py plan-list`, `add-plan --confirm-write yes`, `confirm-plan --confirm-write yes`
2. Read participating products from `data` in the plan response. A zero `count` does not make a nonempty `data` list empty. Require successful HTTP and business status plus the expected response shape.
3. Compute required product codes from the resolved application metadata. Match plans by exact `product` code and `releaseVersionId`, not by display name or case-insensitive comparison.
4. Add only missing product codes with `add-plan --product <exact-code> --confirm-write yes`; track rows added in this run. The helper validates codes before posting and verifies participation by read-back.
5. For each product line added in this run:
   - re-read `/view/plan/getPlanList` after `savePlan`;
   - require one visible row with the exact product code, release ID and a concrete row ID;
   - call `POST /view/plan/updateProductStatus` with JSON body `{ "id": "<plan row id>" }`;
   - expect `{ "code": 200, "msg": "OK" }`.
6. Re-read `/view/plan/getPlanList` and verify the added product lines are present with `productCheck = 1` before continuing to `变更应用`; record `productCheckUser` when present.

Do not call `/view/plan/updateProductStatus` for product lines that were already present before this run unless the user explicitly asks; this step is the API equivalent of clicking the row operation `product line update confirm` for newly added participation.

Inherited application rows do not prove participation. A `200` save response or “产品线已参与本次发版” with no matching plan on read-back is an inconsistency. Preserve old applications and report it; do not repeatedly join, delete applications, guess hidden IDs, or change another product to get past the check. If the user allows ignoring a bad record, continue only when the required product has its own valid visible plan.

After an administrator repairs the data, re-read release/plan/application state and resume the already-authorized operation. Do not assume old IDs still exist or repeat a completed build. A record being backed up does not guarantee the API can restore it: restoration has the same plan/status/build dependencies as insertion.

## 变更应用

Use this for application changes after Jenkins has built the application.

For each application:

1. Prefer the application APIs over UI:
   - `GET /view/application/getApplicationList?releaseVersionId=<id>&page=1&limit=200`
   - `GET /view/application/getProductList`
   - `GET /view/application/getApplicationListByProduct?productCode=<code>`
   - `GET /view/application/getApplicationVersionListByApplicationId?applicationId=<applicationId>`
   - `GET /view/application/getApplicationBuildIdListByApplicationId?buildId=<applicationVersionId>`
   - `POST /view/application/saveOrUpdateReleaseApplications`
   - `POST /view/application/delReleaseApplication`
   - Preferred replacement command: `releasego_http_session.py replace-app ... --backup <new-json-path> --confirm-write yes`.
   - Read-only commands: `app-list`, `apps-by-product`, `application-versions`, `application-build-ids`.
   - `save-app` and `delete-app` are lower-level explicit operations; do not hand-chain them to bypass replacement checks.
2. Locate existing release rows by exact application name/artifact/applicationId. Record any old row's `releaseApplicationsId`, tag, and Build ID before changing it.
3. Resolve the correct application definition:
   - Product comes from the participation mapping above.
   - Use `/getApplicationListByProduct` to find candidate `applicationId` values.
   - If multiple definitions share the same artifact, match the Jenkins `buildNumber` and `buildTag` through the application version/build APIs before saving.
4. Resolve `applicationVersionId` by matching `scmTag` to the Jenkins build tag.
5. Resolve `buildNumber` by matching both `buildNumber` and `buildTag` in `/getApplicationBuildIdListByApplicationId`.
6. Before any replacement deletion, use `replace-app` to validate all of the following:
   - exact release name and ID, with status `0`;
   - exact product code in the current catalog and application membership under that code;
   - a unique visible plan for that release/product (an existing unconfirmed row is not automatically confirmed by the helper; follow the participation workflow for rows added in this run);
   - new version/build metadata matching the application, build number, tag and commit;
   - at most one existing target application row, with a verified release ID and concrete row ID;
   - old version/build metadata still available for recovery if a row will be replaced;
   - a new, non-overwriting snapshot containing the old row identity, restore parameters and requested target, without credentials or unrelated application data.
   Recheck state immediately before deletion. If the requested target is already installed, return a verified no-op. If a prerequisite is absent or inconsistent, **zero deletes** is the required outcome.
   `releaseVersionId` identifies the row's owning release. `sinceReleaseVersionId` records where that application version originated; copied baseline rows legitimately retain an older value. Do not reject or modify them solely because those two fields differ.
7. Only after preflight, delete the exact old row if needed and save the new build. The underlying save body is:
   ```json
   {
     "releaseVersionId": "<release id>",
     "id": "",
     "productCode": "<product code>",
     "applicationId": "<application id>",
     "applicationVersionId": "<application version id>",
     "buildNumber": "<Jenkins build number>"
   }
   ```
   Do not rely on `id` for in-place replacement: the endpoint can reject even the same application as a duplicate. That response is a workflow signal, not proof that it is safe to delete.
8. Re-read `/view/application/getApplicationList` and verify the new row has the requested `scmTag`, `buildNumber`, package fields, and `sinceReleaseVersionId` when applicable.
9. On an error or timeout, read back before retrying. After an ambiguous delete, stop if the old row remains or another row appears; if it is verified absent, recheck prerequisites before continuing the already-authorized save. After an ambiguous save, if the new target is already present, do not write again. If a different row appears, preserve it and report concurrent change. If the row is missing and the old target plus current prerequisites are still valid, attempt one restore and verify it. Stop further mutations if recovery fails; report whether the row is restored, missing or unknown, preserve the redacted HTTP/business error, and give the snapshot path. Delete/add is not a transaction and cannot guarantee rollback.
10. Report success only after the target release has exactly the intended row. Do not delete additional rows to make verification pass, use a published/released version copy operation, or modify service databases as an improvised recovery step.

Example (replace values with identities already resolved from APIs):

```text
python scripts/releasego_http_session.py replace-app --release-version <exact-version> --release-version-id <id> --product-code <catalog-code> --application-id <application-id> --application-version-id <version-id> --build-number <build-number> --backup <new-backup.json> --confirm-write yes
```

The fresh `replace-app` CLI session explicitly logs in through the configured verified HTTPS origin. It never follows an HTTP downgrade or sends credentials to another origin. When composing authenticated API calls directly, keep login and subsequent operations in the same session.

For multi-application Jenkins builds, do not wait for all builds to finish before filling ReleaseGo. Once product-line participation is ready, fill each application as soon as that application's Jenkins build succeeds. Keep monitoring the other builds in parallel and fill their rows when they succeed.

Use the application list JSON endpoint as a verification aid when possible:

`/view/application/getApplicationList?releaseVersionId=<id>&page=1&limit=100`

Relevant JSON fields observed in ReleaseGo include `artifact`, `applicationId`, `scmTag`, `buildNumber`, `buildPackageRepoPath`, `productName`, and `releaseApplicationsId`.

## 变更配置

Use this for schema/config changes. Configs need tags but do not need Jenkins Build ID.

Prefer the API when the ReleaseGo session is already authenticated. Use the UI only as fallback if the API is unavailable or unstable.

For each config:

1. Resolve the release id from the release list API:
   `GET /view/release/getReleaseList?page=1&limit=100&releaseVersion=<version>&status=&releaseForkName=`
2. Fetch the config rows with:
   `GET /view/release/getReleaseConfigList?releaseVersionId=<id>&page=1&limit=200`
3. Locate the row whose `gitId` exactly matches the config project/application name.
4. Update that row with:
   `POST /view/release/SaveOrUpdateReleaseConfig`
   - Body JSON: `id`, `gitId`, `gitTag`, `releaseVersionId`
   - Helper command: `releasego_http_session.py save-config --confirm-write yes`
5. Expect a success response of `{ "code": 200, "msg": "OK" }`.
6. Re-fetch the config list and verify the row now has the requested `gitTag`.
7. If any config API response is unauthenticated, recover login once and retry the original API call.
8. If the API is unavailable or unstable after auth recovery, use `变更配置` in the UI as fallback.

Use the config list JSON endpoint as a verification aid when possible:

`/view/release/getReleaseConfigList?releaseVersionId=<id>&page=1&limit=200`

Relevant JSON fields observed in ReleaseGo include `id`, `gitId`, `gitTag`, and `assemblyConfig`.

## Report

After filling, report:

- release version and ReleaseGo id;
- status check result (`等待集成`);
- product lines that were already present or added, plus whether newly added lines were confirmed with `productCheck = 1` and `productCheckUser` when available;
- application changes with application name, product line, git tag, and Build ID;
- config changes with `gitId` and `gitTag`;
- verification method and result.

## Stop Points

Stop with a specific reason when:

- release version is missing;
- release is not found or multiple non-exact matches appear;
- release status is not `等待集成`;
- login recovery retried once but the target ReleaseGo page/API is still unauthenticated;
- required application tag or Build ID is missing;
- required config tag is missing;
- 4.0 / 观云 product line is unknown;
- exact app/config row cannot be found;
- product-line update confirmation fails or the refreshed plan list does not show `productCheck = 1` for a product line added in this run;
- config save API does not return `code: 200`;
- delete/add/save fails;
- post-save verification does not match the requested tag or Build ID.
- a participation response claims success/already joined but the exact plan is absent or ambiguous on read-back;
- the product value is not an exact catalog code, or application ownership does not match it;
- replacement preflight or recovery metadata cannot be verified;
- rollback fails or the actual application row state becomes uncertain. Report this immediately and preserve the recovery snapshot.
