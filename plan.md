# plan.md: Draft release surfaces for APK downloads

## Goal

Surface CI-built APKs as downloadable links in the GitHub Actions run summary, without Actions artifact storage (billed on private repos) and without cluttering the published Releases page. APKs already live on the ghcr builds shelf (`run-{N}` tags, pushed by `ci-build-unity`); this adds GitHub Release draft mirrors that pull from the shelf and expose `browser_download_url` links in `$GITHUB_STEP_SUMMARY`.

unity-devkit and ci-devkit are unchanged. All new logic lives in release-devkit (the GitHub-coupled devkit). The ghcr shelf stays canonical — drafts are a UI mirror, not a replacement.

## Pinned decisions

1. **ghcr shelf stays canonical.** `ci-build-unity` (unity-devkit) keeps pushing `run-{N}` to `ghcr.io/{owner}/{repo}/builds/{project}-{platform}:{tag}`. `install` keeps pulling from it. `create-release` keeps stapling from it on main. No unity-devkit or ci-devkit changes.
2. **Three surfaces:**
   - **PR draft** (`pr-{N}` tag): one draft release per open PR. Each CI run appends a run-suffixed asset (no clobber of prior runs) — all builds visible, not just latest. Deleted on PR close.
   - **Dev draft** (`dev-builds` tag): one rolling draft accumulating every merged PR's build since the last promotion to main. Each merge appends a run-suffixed asset. Reset (deleted) on promotion to main.
   - **Main release** (CalVer `YYYY.MM.N`): unchanged — existing `create-release`, one asset per platform (the promoted build).
3. **Dispatch runs skip.** `workflow_dispatch` (no PR number) produces no draft; the APK is on the shelf, retrievable via the `install` CLI verb. The PR-surface verb runs only on PR events (`if: github.event.pull_request`).
4. **Merged PR branches are deleted by the merge-bot** after the FF push (new logic in `merge_gate.py`). Abandoned PRs (closed without merge) keep their branch; only the `pr-{N}` draft is deleted.
5. **Drafts are `draft: true`** — hidden from the published Releases page. `prerelease`/`make_latest` are not set (drafts don't claim Latest).
6. **Asset naming:** drafts use `{stem}-run-{N}.{ext}` where stem = configured `name` without extension (e.g. `MakeItSing-AndroidMobile-run-42.apk`); when `name` is unset, stem = the selected source file's stem. The main CalVer release keeps the bare configured `name` (or source name). The dev draft may additionally include the PR number (`{stem}-pr-{pr}-run-{N}.{ext}`) when resolvable — navigational aid, not load-bearing.
7. **Tag collision avoidance:** the dev draft tag is `dev-builds` (not `dev`, which collides with the `dev` branch in the refs namespace). PR drafts are `pr-{N}` (low collision risk; no `pr-*` branch convention).
8. **Permissions:** all new verbs use `github.token` (no App token). Release/tag operations aren't blocked by the evergreen-dev ruleset (which protects the `dev` branch, not tags). `packages: read` to pull from the shelf; `actions: read` where `matched_ci_run_number` queries the Actions API; `contents: write` to create/delete releases and tags.

## Architecture

```
                ghcr builds shelf (canonical, immutable)
                ghcr.io/{owner}/{repo}/builds/{project}-{platform}:run-{N}
                              │
          ┌───────────────────┼──────────────────────────┐
          │                   │                          │
   update-pr-draft-release  update-dev-draft-release  create-release (existing)
   (integrate.yml, PR)      (release.yml, dev-push)   (release.yml, main-push)
          │                   │                          │
          ▼                   ▼                          ▼
   pr-{N} draft          dev-builds draft          CalVer published release
   (append per run)      (append per merge)        (one asset, the promoted build)
          │                   │
          ▼                   ▼
   delete-pr-draft-release  reset-dev-draft-release-release
   (PR close)               (main push, after release)
```

## release-devkit changes

### Shared helper: extract `collect_build_assets` pull logic

`create_release.py:92-122` (`collect_build_assets`) iterates `apps[].builds.artifacts`, calls `pull_build` per artifact, and stages files via `select_artifact_file` (`:141-153`). Extract this pull-and-stage loop into a shared helper (e.g. `pull_build_assets(publish_config, run_number, settings) -> list[(artifact, staged_path)]`) so `create-release`, `update-pr-draft-release`, and `update-dev-draft-release` all reuse it. Avoid duplicating the `pull_build` + `select_artifact_file` iteration.

### New verb: `update-pr-draft-release` (PR mode)

Runs in `integrate.yml` after `build-unity`.

Inputs (flags): `--pr-number <N>`, `--run-number <M>`.
- Derives draft tag `pr-{N}`.
- Calls the shared pull helper with run number M → staged asset paths.
- Creates the `pr-{N}` draft release if absent (`gh release create pr-{N} --draft --target <github_sha>`); idempotent on existence.
- Uploads each artifact as `{stem}-run-{M}.{ext}` via `gh release upload pr-{N} <files> --clobber`. `--clobber` is required: a re-run of the same CI run (same M) overwrites the same-named asset; a new run (M+1) appends a uniquely-named asset.
- Emits each asset's `browser_download_url` to `$GITHUB_STEP_SUMMARY` as a markdown link, via `outputs.append_line` (`outputs.py:6-9`, the same door `validate-release-plan`/`release`/`publish-prerelease` use).
- Wraps work in `ci_step` (consistent with `create-release`).
- No-op when `apps[].builds` is empty (guard like `collect_build_assets` at `create_release.py:93-95`).

### New verb: `update-dev-draft-release` (dev mode)

Runs in `release.yml` dev-push job (alongside `publish-prerelease`).

Inputs: none (uses ambient `GITHUB_SHA` + config's `ci_workflow`).
- Calls `matched_ci_run_number(repository, github_sha, ci_workflow)` (reuse `create_release.py:125-138`) → M. Fails loudly on no matched run (reuse the `::error::` at `:134` — "cannot surface untested code").
- Derives draft tag `dev-builds`.
- Calls the shared pull helper with run number M → staged asset paths.
- Creates the `dev-builds` draft release if absent; uploads as `{stem}-run-{M}.{ext}` (optionally `{stem}-pr-{pr}-run-{M}.{ext}` if the PR number is resolvable from the matched run's metadata — see Open notes) via `gh release upload dev-builds <files> --clobber`.
- Emits URLs to `$GITHUB_STEP_SUMMARY`.

### New verb: `delete-pr-draft-release`

Runs in new `pr-cleanup.yml` on `pull_request: [closed]`.

Inputs (flags): `--pr-number <N>`.
- Derives draft tag `pr-{N}`.
- `gh release delete pr-{N} --cleanup-tag --yes` if it exists (check via `gh release view`; tolerate "not found" — abandoned PR that never built).
- Does NOT delete the branch (abandoned branches stay; merged branches already deleted by merge-bot).

### New verb: `reset-dev-draft-release`

Runs in `release.yml` main-push job, after `release` (which calls `create-release` internally).

Inputs: none.
- `gh release delete dev-builds --cleanup-tag --yes` if it exists.
- No-op if absent (no dev builds since last release).
- Gated on the `release` step's success (`if: success()` on the step or job-level needs) — only reset once the CalVer release is cut.

### merge-gate modification: delete merged branch

In `merge_gate.py`, after the FF push at line 97, add head-branch deletion:

```python
head_ref = bash_output(f"gh pr view {pr_number} --json headRefName --jq .headRefName").strip()
if head_ref and head_ref not in (BASE_BRANCH, "main"):
    if bash_check(f"{GIT_COMMAND} ls-remote --heads origin {head_ref}"):
        bash(f"{GIT_COMMAND} push origin --delete {head_ref}")
        print(f"  deleted branch {head_ref}")
```

Guard against `dev`/`main`. Use `GIT_COMMAND` (App token, already has `Contents: write` — it pushes to dev at line 97). Check existence first (`bash_check` on `ls-remote --heads`) to tolerate races with GitHub's auto-delete-head-branches setting.

### AGENTS.md (release-devkit) — prose

- Add the four new verbs to the Commands table.
- Document the three-surface architecture (PR draft / dev draft / main release) and the ghcr-shelf-as-canonical invariant.
- Document the tag grammar (`pr-{N}`, `dev-builds`; `dev-builds` ≠ `dev` branch).
- Document the cleanup/reset lifecycle and the merge-gate branch deletion.
- Document the canonical consumer workflow shapes (so `lint-workflows` + consumers replicate).
- Prose commit, separate from code.

## Consumer workflow template changes

(Canonical shapes `lint-workflows` will enforce. release-devkit's AGENTS.md owns the contract; consumers replicate.)

### integrate.yml — new `update-pr-draft-release` job

```yaml
  update-pr-draft-release:
    needs: [build-unity]
    if: github.event.pull_request
    permissions: {contents: write, packages: read}
    runs-on: ubuntu-latest
    steps:
      - *checkout
      - *uv-restore
      - *setup-release-devkit
      - run: >-
          uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev update-pr-draft-release
          --pr-number ${{ github.event.pull_request.number }}
          --run-number ${{ github.run_number }}
        env:
          GITHUB_TOKEN: ${{ github.token }}
```

`needs: [build-unity]` where `build-unity` is the matrix — the surface job runs once after all matrix legs complete, iterating all `apps[].builds.artifacts` in one job (avoids concurrent uploads to the same draft from matrix legs). Mirrors how `create-release`'s `collect_build_assets` iterates artifacts.

### release.yml — dev-push: new `update-dev-draft-release` step

Add to the `publish-prerelease` job (or a sibling on the `dev` gate), after `publish-prerelease`:

```yaml
      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev update-dev-draft-release
        env:
          GITHUB_TOKEN: ${{ github.token }}
```

Job permissions: `contents: write`, `packages: read`, `actions: read` (for `matched_ci_run_number`).

### release.yml — main-push: new `reset-dev-draft-release` step

Add to the `release` job, after the `release` verb step:

```yaml
      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev reset-dev-draft-release
        env:
          GITHUB_TOKEN: ${{ github.token }}
```

`contents: write` already on the `release` job.

### New workflow: pr-cleanup.yml

```yaml
name: PR cleanup
on:
  pull_request:
    branches: [dev]
    types: [closed]
permissions:
  contents: write
jobs:
  cleanup:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v7
        with: {enable-cache: true, save-cache: "false"}
      - uses: ./.github/actions/setup-release-devkit
      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev delete-pr-draft-release --pr-number ${{ github.event.pull_request.number }}
        env:
          GITHUB_TOKEN: ${{ github.token }}
```

### lint-workflows updates

- Validate `update-pr-draft-release` job: `if: github.event.pull_request`, `needs: [build-unity]`, canonical invocation + env.
- Validate `update-dev-draft-release` and `reset-dev-draft-release` steps in `release.yml` (canonical spellings, env, gating).
- Validate `pr-cleanup.yml`: trigger `pull_request: [closed]`, the `delete-pr-draft-release` invocation.
- Add the new verbs to the per-verb flag/env contract that `lint-workflows` enforces.

## Tests

`tests/` already exists. Add unit tests for:
- `update-pr-draft-release`: tag derivation (`pr-{N}`), asset naming (`{stem}-run-{M}`), no-op on empty builds, summary emission, `--clobber` usage.
- `update-dev-draft-release`: `matched_ci_run_number` integration, tag `dev-builds`, asset naming, loud failure on no matched run.
- `delete-pr-draft-release`: tag derivation, no-op on missing draft, `--cleanup-tag` usage.
- `reset-dev-draft-release`: no-op on missing draft.
- `merge-gate` branch deletion: guard against `dev`/`main`, head-ref resolution, tolerance of already-deleted branch.
- Shared `pull_build_assets` helper: iteration over artifacts, `select_artifact_file` reuse.

Mock `bash`/`bash_output`/`bash_check` per existing test patterns.

## Implementation order

1. **release-devkit** (this repo): extract shared pull helper → new verbs → `merge-gate` modification → tests → AGENTS.md. Commit prose (AGENTS.md) and code (verbs/tests/merge-gate) separately per the prose/code split.
2. **Consumer repos** (make-it-sing, placeframe-capture-tool, etc.): bump the `setup-release-devkit` wrapper SHA pin to the release-devkit commit from step 1; add the workflow jobs; update consumer AGENTS.md. Per-consumer work — release-devkit's AGENTS.md documents the canonical shapes so consumers replicate.

## Open implementation notes

- **PR auto-close on FF push:** when the merge-bot FF-pushes dev to the PR head, GitHub may auto-close the PR (detecting the head commits in the base), firing `pull_request: [closed]` for `delete-pr-draft-release`. Verify empirically; if GitHub does not auto-close reliably for raw FF pushes, the `pr-{N}` draft lingers. Fallback: add an explicit `gh pr close {pr_number}` step in `merge-gate` after branch deletion — but note `gh pr close` marks "closed" not "merged" (GitHub's auto-close marks "merged"), so prefer relying on auto-close if it works.
- **Verb granularity:** this plan proposes four verbs (`update-pr-draft-release`, `update-dev-draft-release`, `delete-pr-draft-release`, `reset-dev-draft-release`) plus the `merge-gate` modification. If a unified shape reads cleaner (e.g., one `update-pr-draft-release` with a `--mode` flag, one `delete-draft` with a `--tag` flag), the implementer may refactor — the behaviors are the contract, not the verb count.
- **Dev draft asset PR-number:** optionally include the PR number in the dev draft's asset names (`{stem}-pr-{pr}-run-{M}.{ext}`) by resolving it from the matched CI run's metadata (`gh run view {run_id} --json head_branch` → PR lookup, or `gh api /repos/{repo}/commits/{sha}/pulls`). If the lookup is unreliable or costly, fall back to run-number-only naming.
- **`--clobber` semantics:** `gh release upload --clobber` overwrites same-named assets (re-run safety) and appends uniquely-named ones (new-run append). Always pass `--clobber` — it does not delete non-matching assets, so prior runs' assets accumulate as intended.

## Commit discipline

Per AGENTS-SHARED: prose and code in separate commits. AGENTS.md updates are prose; verb code, tests, and the `merge-gate` modification are code. No trailers. One subject line under 72 chars, specific (name the actual verbs/changes, not "update release-devkit").
