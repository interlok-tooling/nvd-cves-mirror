# VulnCheck Migration Handover

## Objective

Migrate the NVD cache mirror workflow away from the NIST NVD 2.0 paginated API and onto VulnCheck NVD++ bulk backups, using a branch-first rollout so the change can be tested before merging to `main`.

## Executive Summary

- The old NIST-backed workflow became operationally unreliable after the June 2026 NVD changes
- A replacement workflow using VulnCheck NVD++ has already been implemented on branch `vulncheck`
- That code change is pushed, but local dry-run testing found that it is not yet correct
- The remaining work is now to fix the workflow logic, re-test locally, then run it in GitHub Actions and validate the resulting `nvd-cache` branch contents
- There are two separate blockers: local GitHub CLI workflow dispatch permissions, and a real format/implementation problem in the current migration draft

## Current Status

- Working branch: `vulncheck`
- Remote branch: `origin/vulncheck`
- Latest migration commit: `d05cf64` (`feat: add vulncheck canary feed converter`)
- Repository secret `VULNCHECK_API_TOKEN` has already been configured in GitHub Actions
- The workflow file has been replaced on the branch and validates cleanly in the editor
- A local converter script has now been added to transform VulnCheck backup ZIP files into a Dependency Check-compatible feed layout
- The branch workflow has been reworked into a canary publisher targeting `nvd-cache-vulncheck`, not `nvd-cache`
- The top-level repository README has been updated to describe the canary branch correctly
- Local API testing with `VULNCHECK_API_TOKEN` succeeded
- Local dry-run testing showed the original direct-download workflow implementation was not compatible as written
- The replacement conversion-based approach is now implemented locally

## Local Dry-Run Findings On 2026-06-26

Using the token from the Windows user environment, a local test was run against the VulnCheck backup API.

What was confirmed:

1. The API token works
2. The backup index endpoint responds successfully
3. The index currently returns a single pre-signed ZIP download URL
4. The ZIP can be downloaded locally without adding a bearer token to the download request

What was discovered:

1. The backup download URL is already pre-signed
2. Sending an `Authorization: Bearer ...` header to that URL causes the download to fail
3. The current workflow does exactly that, so the download step in its present form will fail
4. The current workflow also derives the filename with `basename "$url"`, which would include the query string from the signed URL rather than just the clean ZIP filename
5. The downloaded ZIP does not contain yearly `nvdcve-YYYY.json.gz` plus `.meta` files
6. Instead, it contains many chunked files named like `nvdcve-2.0-000.json.gz`, `nvdcve-2.0-001.json.gz`, and so on
7. The current `nvd-cache` branch contains `cache.properties` plus per-year `.json.gz` and `.meta` files

Current conclusion:

- The current VulnCheck migration draft is not ready to run as-is
- Even after fixing the signed-URL download bug, the output format appears different from the format currently published on `nvd-cache`
- That means the migration is not just a workflow plumbing change; it may require a format conversion step or a different publishing strategy

Additional evidence:

- Dependency Check's `nvdDatafeedUrl` support is documented around a `vulnz`-generated feed
- The documented example format is `.../nvdcve-{0}.json.gz`
- Dependency Check's code path for datafeed mode expects `cache.properties` and `.meta` files as part of the mirrored feed layout
- This makes the current VulnCheck ZIP layout mismatch a likely real compatibility problem, not just a cosmetic naming difference

## Implementation Added On 2026-06-26

The following implementation work has now been done on branch `vulncheck`:

1. Added `scripts/convert_vulncheck_feed.py`
2. The converter downloads or accepts VulnCheck backup ZIP files
3. The converter transforms the backup into:
   - `nvd_api_cache/cache.properties`
   - `nvd_api_cache/nvdcve-YYYY.json.gz`
   - `nvd_api_cache/nvdcve-YYYY.meta`
   - `nvd_api_cache/nvdcve-modified.json.gz`
   - `nvd_api_cache/nvdcve-modified.meta`
4. The converter preserves the current live feed partitioning rule:
   - files are grouped by CVE `published` year
   - anything published before 2002 is folded into `nvdcve-2002.json.gz`
5. The branch workflow `.github/workflows/nvd-cache.yml` now builds a canary feed and pushes it to `nvd-cache-vulncheck`
6. These changes have been committed and pushed to `origin/vulncheck`

## Local Validation Added On 2026-06-26

Local validation established the following:

1. The VulnCheck ZIP contents can be converted into the expected Dependency Check mirror layout
2. The generated file names and metadata layout now match the current mirror pattern closely
3. A local `dependencyCheckUpdate` run against the current live mirror succeeds even though it logs a few bad-data warnings from upstream CVE content
4. Those warnings include two overlong Mozilla bugzilla reference URLs and one CPE parse issue
5. Those warnings therefore are not unique to the VulnCheck conversion path
6. A local `dependencyCheckUpdate` run against the converted feed initially exposed a feed timestamp formatting mismatch, and the converter was then patched to match the current live feed format more closely
7. After that patch, a final clean rerun should still be treated as required before relying on the canary branch in shared CI

## Repository And Branch Context

- Repository: `interlok-tooling/nvd-cves-mirror`
- Default branch: `main`
- Cache branch written by the workflow: `nvd-cache`
- Test/migration branch: `vulncheck`
- Primary workflow under change: `.github/workflows/nvd-cache.yml`

## Wider Build Context

This mirror is not an isolated repo. It sits in the wider Interlok CI/build chain.

Confirmed upstream context:

1. `adaptris/interlok` has a branch-build workflow at `.github/workflows/gradle-check.yml`
2. That workflow delegates to `interlok-tooling/reusable-workflows/.github/workflows/gradle-check.yml@main`
3. It passes `NVD_API_KEY` into the reusable workflow
4. The reusable workflow runs `./gradlew ... check`
5. The reusable workflow also runs a separate `./gradlew ... dependencyCheckAnalyze`
6. `adaptris/interlok-build-parent` applies the OWASP Dependency Check Gradle plugin in `v5/build.gradle`
7. In that parent build, `check` does not directly depend on `dependencyCheckAnalyze`; the reusable workflow invokes dependency checking as an explicit separate CI step

Important implication:

- Any change to the mirror format can affect more than this repo
- It can affect shared reusable workflows and any Interlok project that relies on the mirrored Dependency Check feed

Additional confirmed detail:

- In `interlok-tooling/reusable-workflows`, the `gradle-publish.yml` workflow already contains a `dependencyCheckAnalyze` step that passes `-PdependencyCheckNvdDatafeedUrl='https://raw.githubusercontent.com/interlok-tooling/nvd-cves-mirror/nvd-cache/nvd_api_cache/'`
- That is direct evidence that this mirror is already treated as part of the wider build pipeline, not just as a standalone experiment

Current practical reading of the estate:

- Some workflow paths still pass only `NVD_API_KEY`
- At least one reusable workflow path already points builds at the `nvd-cves-mirror` feed
- Because of that mixed state, a bad format change here could break builds in a non-obvious way across multiple repositories

## Why The Old Approach Was Replaced

The previous workflow depended on paginated polling of the NIST NVD 2.0 API via `vulnz.jar`. Following the NVD schema/data changes in mid-June 2026, the workflow started failing with long-running timeouts and transport errors. Even with retries and higher JVM memory, runs were hitting the GitHub Actions job limit and not completing.

This migration changes the retrieval model completely:

- Old model: page through the NIST API and build the cache incrementally
- New model: request a VulnCheck backup index once, then download the published backup files directly

The new approach is materially simpler and should avoid the API timeout class of failures entirely.

## Files Changed So Far

- `.github/workflows/nvd-cache.yml`
- `README.md`
- `VULNCHECK-MIGRATION-HANDOVER.md`

## What Changed

### Workflow

The branch workflow now:

1. Checks out the `nvd-cache` branch
2. Reads `VULNCHECK_API_TOKEN` from GitHub Actions secrets
3. Calls the VulnCheck NVD++ backup index endpoint:

   `https://api.vulncheck.com/v3/backup/nist-nvd2`

4. Uses `jq` to extract each backup download URL
5. Downloads all backup files into `./nvd_api_cache`
6. Writes an attribution `README.md` into the `nvd-cache` branch contents
7. Commits the refreshed cache and force-pushes `nvd-cache`

Note:

- This is what the current workflow draft tries to do
- Local dry-run testing has shown that this logic is not yet sufficient

Important implementation detail:

- The workflow checks out the `nvd-cache` branch directly, because that branch is the published mirror output rather than the source branch containing the workflow definition
- Manual testing should still be started from branch `vulncheck`, because that branch contains the updated workflow file definition

### Documentation

The top-level README now explains that the mirror uses VulnCheck NVD++, and that consumers should continue using:

`https://raw.githubusercontent.com/interlok-tooling/nvd-cves-mirror/nvd-cache/nvd_api_cache/`

## Prerequisites For The Team Taking Over

The following must be true before testing or completing the rollout:

1. The repository contains the `VULNCHECK_API_TOKEN` GitHub Actions secret
2. The person triggering or reviewing the run has permission to access repository Actions runs and logs
3. The team understands that the workflow definition lives on `vulncheck` for now, but the output branch it writes to is `nvd-cache`
4. Downstream consumers of the `nvd-cache` feed are known, so compatibility can be confirmed after the first run

## Current Issues / Blockers

### 1. The new workflow has not been run successfully yet

The migration has been coded and pushed, but there has not yet been a successful run of the new branch workflow.

### 2. CLI workflow dispatch is blocked by token permissions

Attempting to trigger the workflow from the command line with:

```bash
gh workflow run nvd-cache.yml --ref vulncheck
```

returns:

```text
HTTP 403: Resource not accessible by personal access token
```

That means the currently configured GitHub CLI token can read repo state, but does not have sufficient Actions/workflow permissions to create a workflow dispatch event.

### 3. Existing `main` workflow runs are still failing

Recent runs visible from the CLI are still on `main`, and the failing scheduled runs are consistent with the original NIST timeout problem.

### 4. End-to-end data compatibility is not yet verified

The migration assumes the VulnCheck NVD++ backup JSON files are suitable for the downstream Dependency Check consumers, but this still needs to be confirmed after the first successful run.

### 5. The current download step is wrong for pre-signed VulnCheck backup URLs

The local dry run showed that the backup index returns a pre-signed URL. Those URLs must be downloaded directly, without adding the bearer token again on the download request. The current workflow still adds an `Authorization` header during download, which causes the request to fail.

### 6. The current filename handling is likely wrong for signed URLs

The current workflow uses `basename "$url"`, but the URL includes a long query string. That means the resulting filename would likely include the query component unless the filename is derived from the URL path only.

### 7. The VulnCheck backup format appears different from the current published cache format

The current `nvd-cache` branch contains:

- `cache.properties`
- yearly files like `nvdcve-2025.json.gz`
- yearly metadata files like `nvdcve-2025.meta`

The VulnCheck ZIP inspected locally contains chunked files like:

- `nvdcve-2.0-000.json.gz`
- `nvdcve-2.0-001.json.gz`
- `nvdcve-2.0-002.json.gz`

No yearly `.meta` files were present in the inspected archive. This is the biggest open problem and may mean downstream consumers cannot use the bundle directly.

### 8. `nvd-cache` branch assumptions should be verified during first run

The workflow currently performs:

```bash
git reset --soft HEAD~1
```

This was carried over from the earlier workflow behavior and assumes the branch history shape is still compatible. It may be harmless, or it may prove unnecessary during validation. If the first VulnCheck run fails around branch state or commit history handling, this is one of the first places to inspect.

### 9. Final end-to-end validation against Dependency Check still needs one clean rerun

The converter and canary workflow are now implemented, and local validation got far enough to prove the structure is close to correct. However, after the final timestamp-format patch, one clean local or CI rerun is still needed so the canary feed can be called validated with confidence.

## Exact State of the Branch

- Branch `vulncheck` exists locally and remotely
- The migration commit is already pushed
- The only current uncommitted workspace edit is this handover note
- YAML validation passed locally in the editor

## Known Good Evidence So Far

- Branch `vulncheck` exists locally and remotely
- Migration commit `f550045` is present on `origin/vulncheck`
- The workflow file parses cleanly in the editor
- The README changes are present locally
- `gh auth status` shows GitHub CLI login is valid for repo access, even though it is not sufficient for workflow dispatch

## What Is Left To Do

### Required next step

Before running this in GitHub Actions, fix the workflow logic based on the local dry-run findings:

1. Do not send an `Authorization` header when downloading the pre-signed backup URL
2. Derive the output filename from the URL path only, not from the full signed URL string
3. Decide how the VulnCheck ZIP contents should be published so that downstream Dependency Check consumers can still use the mirror

Only after that should the workflow be manually triggered in GitHub Actions against the `vulncheck` branch.

### GitHub test step after fixes

Trigger the workflow manually from the GitHub web UI against the `vulncheck` branch:

1. Open the repository Actions page
2. Open the `NVD API Cache` workflow
3. Click `Run workflow`
4. Choose branch `vulncheck`
5. Start the run

This avoids the CLI token permission issue.

If branch selection is not offered in the UI, confirm that GitHub is showing the workflow definition from branch `vulncheck` and that `workflow_dispatch` is enabled for that branch version of the file.

### After the run starts

Verify the logs show:

1. Backup index fetched successfully from VulnCheck
2. Backup file URLs enumerated correctly
3. The signed download URL is fetched without auth-header failure
4. Files are extracted or transformed into the expected published layout
5. Attribution `README.md` written
6. Commit created or `No changes to commit.` if identical
7. Force-push to `nvd-cache` succeeds

### After the run completes

Check the `nvd-cache` branch and confirm:

1. `nvd_api_cache` contains the downloaded backup files
2. The branch contains the attribution `README.md`
3. The mirrored cache layout is compatible with downstream consumers
4. Cache freshness looks acceptable for the 8-hour schedule

## Acceptance Criteria

The migration should be considered complete only when all of the following are true:

1. A manual run from branch `vulncheck` completes successfully
2. The `nvd-cache` branch is updated by that run
3. The cache contents are structurally usable by downstream Dependency Check consumers
4. The run duration is comfortably below the GitHub Actions time limit
5. A subsequent scheduled or manual run continues to succeed without intervention
6. The team is satisfied that VulnCheck update cadence is acceptable for the existing 8-hour schedule

## Suggested Validation Checklist

### GitHub-side

- Workflow completes well under the previous 6-hour limit
- No 524s, H2 resets, or pagination/retry churn
- `VULNCHECK_API_TOKEN` is the only required API secret for the new path

### Data-side

- File naming in `nvd_api_cache` matches what consumers expect
- A downstream Dependency Check consumer can still resolve the mirror feed
- No missing files compared with the old cache layout that consumers relied on
- If the VulnCheck ZIP is chunked, confirm whether a conversion step is needed before publish

### Repository-side

- The `nvd-cache` branch still contains only mirror/output content expected by consumers
- The attribution `README.md` is present on `nvd-cache`
- No accidental source-branch files were pushed into `nvd-cache`

## Risks And Things To Watch

- The VulnCheck backup format may differ in subtle ways from the previous mirrored content
- The VulnCheck backup format may differ in major ways from the previous mirrored content, not just subtle ones
- The branch write strategy uses `--force`, so the first successful run should be reviewed carefully
- If `jq` parsing assumptions are wrong, the workflow may fetch the index successfully but fail before downloading files
- If the workflow keeps the current signed-URL download logic, downloads will fail immediately
- If the branch history assumption behind `git reset --soft HEAD~1` is no longer valid, the run may fail before commit/push

## Recommended Troubleshooting Order

If the first test run fails, inspect in this order:

1. Was `VULNCHECK_API_TOKEN` actually available to the workflow run?
2. Did the index call to `https://api.vulncheck.com/v3/backup/nist-nvd2` succeed?
3. Did `jq -r '.data[].url'` return URLs?
4. Is the workflow incorrectly adding an auth header to a pre-signed download URL?
5. Is the workflow deriving the filename from the URL path correctly?
6. Did file downloads succeed for every URL?
7. Did the workflow extract or transform the ZIP contents into the expected published format?
8. Did the git commit/push step fail due to branch state rather than data download?
9. If git state failed, inspect whether `git reset --soft HEAD~1` is still appropriate

## Suggested Commands For A Future Responder

These are the quickest local commands to re-establish context:

```bash
git checkout vulncheck
git pull --ff-only
git log --oneline --decorate -5
gh auth status
gh run list --workflow nvd-cache.yml --limit 10
```

If the team has a token with sufficient workflow scope, they can also try:

```bash
gh workflow run nvd-cache.yml --ref vulncheck
```

If this returns `HTTP 403: Resource not accessible by personal access token`, use the GitHub web UI instead.

## If Another Session Needs To Pick This Up

Start with these checks:

```bash
git checkout vulncheck
git pull --ff-only
gh run list --workflow nvd-cache.yml --limit 10
```

Then inspect:

- Whether a run has been started for branch `vulncheck`
- Whether `nvd-cache` was updated by that run
- Whether downstream consumers still work against the mirrored feed

## Probable Final Steps After Successful Validation

1. Merge `vulncheck` into `main`
2. Trigger the workflow from `main`
3. Confirm `nvd-cache` continues updating on schedule
4. Remove the old `NVD_API_KEY` secret if no longer needed
5. Optionally remove any stale notes or references to the old NIST polling approach

## Ownership Notes For Handover

The next team should treat this work as being in the validation and rollout phase, not the implementation phase. The code migration is largely complete. The remaining value is in:

1. Running the new workflow safely
2. Verifying the produced cache is compatible
3. Confirming ongoing operational reliability
4. Merging and cleaning up the legacy secret/config once proven

## Recommended Rollout Plan For The Wider Pipeline

The least painful way to trial this is not to switch the whole estate at once.

### Key confirmed fact

The downstream Interlok component builds already support a mirrored-feed override.

Examples confirmed from downstream `build.gradle` files:

- `dependencyCheck.nvd.apiKey = System.getenv("NVD_API_KEY")`
- `dependencyCheck.nvd.datafeedUrl = project.findProperty("dependencyCheckNvdDatafeedUrl")`

That means a workflow can opt into the mirror by passing:

`-PdependencyCheckNvdDatafeedUrl=https://raw.githubusercontent.com/interlok-tooling/nvd-cves-mirror/<branch-or-path>/nvd_api_cache/`

without changing every downstream build script.

### Recommended strategy

1. Do not replace the existing `nvd-cache` output immediately
2. Create a canary path for the new VulnCheck-backed feed
3. Make the reusable workflow opt into that canary path only on selected branches/repos
4. Validate on one or two downstream repos first
5. Only then promote the new feed to the main shared path

### Suggested staged plan

#### Stage 1: Fix and prove the mirror producer in isolation

Before touching shared CI:

1. Fix the current VulnCheck workflow logic issues
2. Determine whether the VulnCheck ZIP can be transformed into the current Dependency Check mirror layout
3. Publish the transformed output to a separate branch or separate directory, not `nvd-cache`

Recommended names:

- branch option: `nvd-cache-vulncheck`
- directory option on a separate branch: `nvd_api_cache_vulncheck`

The important thing is that the canary feed must have a different raw GitHub URL from the current production feed.

#### Stage 2: Add opt-in support to reusable workflows

Update `interlok-tooling/reusable-workflows/.github/workflows/gradle-check.yml` so dependency check can be pointed at a specific mirrored feed URL by workflow input.

Suggested input:

- `dependency-check-nvd-datafeed-url`

Suggested behaviour:

1. If the input is empty, keep the current behaviour
2. If the input is set, pass `-PdependencyCheckNvdDatafeedUrl=<value>` to `dependencyCheckAnalyze`

This keeps the change low-risk because only opt-in callers use the new feed.

#### Stage 3: Test a single downstream canary repo

Pick one ordinary downstream component repo and create a branch-only canary.

Recommended candidate: `adaptris/interlok-filesystem`

Reason:

1. It uses the standard reusable `gradle-check.yml`
2. Its `build.gradle` already supports `dependencyCheckNvdDatafeedUrl`
3. It looks like a fairly normal component build, which makes it a better first canary than a more unusual integration

How to test it:

1. Create a branch in `interlok-tooling/reusable-workflows` with the opt-in workflow change
2. Create a branch in `adaptris/interlok-filesystem`
3. In that branch workflow, point `uses:` at the reusable workflow branch instead of `@main`
4. Pass the canary feed URL as the workflow input
5. Push a harmless change and inspect the `dependencyCheckAnalyze` step

Success criteria for the canary:

1. Dependency Check downloads from the mirrored feed instead of timing out on NVD
2. The feed format is accepted without parser/update failures
3. The build outcome is then determined by actual dependency findings, not by NVD transport issues

#### Stage 4: Test a second repo with a different profile

After the first canary passes, test a second repo.

Possible second candidate: `adaptris/interlok-nats`

Reason:

1. It uses the same reusable workflow pattern
2. It has a different dependency set
3. Passing there gives more confidence that the feed is generally usable across the estate

#### Stage 5: Promote gradually

Once the canaries are good:

1. Merge the reusable workflow opt-in support
2. Optionally switch more downstream repos by passing the mirror URL explicitly first
3. When confidence is high, make the shared default point to the new mirror output
4. Only then retire the old NIST-based mirror path

## Practical Recommendation On Repo Choice

For the first downstream proof, `interlok-filesystem` is the better canary than `interlok-nats`.

Reason:

1. It looks more typical of the general component build pattern
2. It already supports the mirror property in the same way as the others
3. It is less likely to confuse the trial with repo-specific integration quirks

After that, use `interlok-nats` as a second canary.

## Important Decision Point

There are really two separate changes here:

1. Change the source of NVD data from NIST to VulnCheck
2. Change how the wider build pipeline consumes the mirrored feed

These should be rolled out separately.

Best order:

1. First prove that the mirror output is Dependency Check compatible
2. Then prove one downstream pipeline can consume it via opt-in workflow changes
3. Then expand usage

If those are combined into one big switch, it will be harder to tell whether failures come from feed production, feed format, or reusable workflow integration.