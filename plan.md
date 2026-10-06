# Refactor: Eliminate run_number, unify on run_id

## Problem

`run_number` (`github.run_number`) is per-workflow-file. `integrate.yml`'s run_number 42 and `release.yml`'s run_number 42 are different runs — different counters for different workflows. The builds shelf tag `run-{N}` is pushed by `ci-build-unity` in `integrate.yml` using `integrate.yml`'s `run_number`. When `release`/`prerelease` (which run in `release.yml`) pass `github.run_number` as `--run-number`, they pass a different counter — the shelf tag won't match. This is a silent correctness bug in the current code: the recent change that added `--run-number` to release and prerelease (replacing the internal `matched_ci_run_number` call) means the shelf pull now uses the wrong tag.

`run_id` (`github.run_id`) is unique across the entire repo — no collision between workflows. Switching to `run_id` everywhere eliminates this class of bug.

## Current state (what's wrong)

### Two different values serving overlapping purposes

- `run_number` (`github.run_number`): sequential counter per workflow file. Used for the builds shelf tag `run-{N}`, asset filenames `{stem}-run-{N}.{ext}`, app build-metadata stamp `{base}+{N}`, and draft section anchors/heading text in some verbs.
- `run_id` (`github.run_id`): unique ID per workflow run across the repo. Used for dev version strings (`-dev.{id}`), the Actions URL (`.../actions/runs/{id}`), and draft section anchors in prerelease.

### Per-verb usage (current)

| Verb | Takes | run_number used for | run_id used for | Calls matched_ci_run_number? |
|---|---|---|---|---|
| `get-app-version` | `--run-number` | build metadata stamp `{base}+{N}` | — | no |
| `prerelease` | `--run-number`, `--run-id` | shelf pull, draft asset upload, heading text | dev version, draft anchor | yes (for html_url only, discards run_number) |
| `release` | `--run-number` | shelf pull (build assets + digest manifest) | — | no (removed in recent change — BUG) |
| `update-pr-draft-release` | `--run-number`, `--run-id` | shelf pull, heading text, draft anchor | actions URL | no |

### The regression

The recent commit that added `--run-number` to release and prerelease (and removed `matched_ci_run_number` from release) introduced a regression: `release` and `prerelease` now take `--run-number ${{ github.run_number }}` from `release.yml`, but the shelf tag was pushed by `integrate.yml`'s `github.run_number`. Different workflow files, different counters — the shelf pull uses the wrong tag.

### The inconsistency

- `prerelease`'s draft anchor uses `run_id` (`run-{run_id}`).
- `update_pr_draft`'s draft anchor uses `run_number` (`run-{resolved_run_number}`).
- `prerelease`'s heading says "Integrate run #{run_number}" (uses the CLI-provided run_number, not the matched one).
- `update_pr_draft`'s heading says "Run #{resolved_run_number}" with a URL constructed from `run_id`.
- `release` doesn't use `run_id` at all.

## Target state

One value: `run_id` (`github.run_id`). `run_number` ceases to exist in the release-devkit contract. Every `--run-number` flag becomes `--run-id`. The shelf tag, dev version string, draft anchor, heading link, asset filename, and build metadata stamp all use `run_id`.

### Per-verb target

| Verb | Takes | run_id used for | Resolves integrate run_id? |
|---|---|---|---|
| `get-app-version` | `--run-id` | build metadata stamp `{base}+{id}` | no (runs in integrate.yml, own id is correct) |
| `prerelease` | `--run-id` | dev version, shelf pull, draft assets, heading text + URL, draft anchor | yes (must resolve the integrate run's id from the SHA) |
| `release` | `--run-id` | shelf pull (build assets + digest manifest), heading text + URL | yes (must resolve the integrate run's id from the SHA) |
| `update-pr-draft-release` | `--run-id` (only run flag) | shelf pull, heading text + URL, draft anchor | no (runs in integrate.yml, own id is correct) |

### Resolution mechanism

`release` and `prerelease` run in `release.yml` (push to dev/main). They need the integrate run's `run_id` to pull from the correct shelf tag. `matched_ci_run_number` (renamed to `matched_ci_run`) currently queries the Actions API for `run_number` — change the jq to extract `id` (the run ID) instead of `run_number`. Returns `(run_id: str, html_url: str)`.

`update_pr_draft` and `get_app_version` run in `integrate.yml`. Their own `github.run_id` IS the integrate run's ID. No lookup needed.

## Changes required

### 1. ci-devkit (cross-repo, coordinate first)

`ci-build-unity` pushes the builds shelf tag as `run-{github.run_number}`. Change to `run-{github.run_id}`. This is the shelf tag format change that all consumers must align with.

Also: any `install` job or other ci-devkit code that pulls from the shelf using `run_number` must switch to `run_id`.

### 2. builds.py

- `matched_ci_run_number` → rename to `matched_ci_run`. Change the jq from `.workflow_runs[0].run_number` to `.workflow_runs[0].id`. Return type stays `tuple[str, str]` but now returns `(run_id, html_url)`.
- `MatchedRun` model: rename `run_number` field to `id` (or `run_id`).
- `pull_build_assets`: `build_tag = f"run-{run_number}"` → `f"run-{run_id}"`. Parameter name changes from `run_number` to `run_id`.
- `pull_digest_manifest`: `tag = f"run-{run_number}"` → `f"run-{run_id}"`. Parameter name changes from `run_number` to `run_id`.

### 3. drafts.py

- `publish_draft_assets`: parameter `run_number` → `run_id`. Asset naming `f"{stem}-run-{run_number}{suffix}"` → `f"{stem}-run-{run_id}{suffix}"`.

### 4. verbs/prerelease.py

- Remove `--run-number` flag. Keep `--run-id` (already exists).
- Call `matched_ci_run(repository, sha, publish_config.ci_workflow)` → returns `(run_id, html_url)`. Use `run_id` for shelf pull and draft assets. Use `html_url` for heading link. Use `run_id` (from CLI, for dev version) — wait, the dev version uses the CURRENT run's `run_id` (from `release.yml`), not the integrate run's. The dev version needs to be unique per prerelease run, not per integrate run. So `--run-id` (from `github.run_id` in `release.yml`) is correct for dev versions. The `matched_ci_run` result is used only for the shelf pull (shelf tag) and the heading URL.
- Actually: the dev version (`DevStrategy(run_id)`) uses the CURRENT run's ID for uniqueness — that's correct, it should be unique per prerelease run. The shelf pull needs the INTEGRATE run's ID. The heading should link to the integrate run. So prerelease needs TWO run IDs: its own (for dev version + anchor) and the matched integrate run's (for shelf pull + heading). Keep both: `--run-id` for the current run, `matched_ci_run` for the integrate run.
- Shelf pull: `pull_digest_manifest(publish_config.builds_registry, matched_run_id, actor, token)` — uses the matched integrate run's ID.
- Draft assets: `publish_draft_assets(draft_config, matched_run_id, ...)` — uses the matched integrate run's ID.
- Heading: `f"[Integrate run #{matched_run_id}]({html_url})"` — uses the matched integrate run's ID and URL.
- Dev version: `DevStrategy(run_id)` — uses the CURRENT run's ID (from `--run-id`).
- Draft anchor: `f"run-{run_id}"` — uses the CURRENT run's ID (already the case).

### 5. verbs/release.py

- `--run-number` → `--run-id`. The `--run-id` is the current release run's ID.
- Call `matched_ci_run(repository, sha, publish_config.ci_workflow)` → returns `(matched_run_id, html_url)`. Use `matched_run_id` for shelf pull (build assets + digest manifest). Use `html_url` for heading if needed (release currently doesn't have a heading — it creates a GitHub Release with notes, not a draft section).
- `pull_build_assets(publish_config, matched_run_id, actor, token)`.
- `pull_digest_manifest(publish_config.builds_registry, matched_run_id, actor, token)`.

### 6. verbs/update_pr_draft.py

- Remove `--run-number`. Keep `--run-id` (already exists, currently typed `str` — change to `int` for consistency).
- `resolved_run_id = str(run_id)` — used for shelf pull, heading text, draft anchor, asset naming.
- `run_url = f"https://github.com/{repository}/actions/runs/{run_id}"` — already constructs URL from run_id. No `matched_ci_run` call needed.
- `publish_draft_assets(publish_config, resolved_run_id, ...)`.
- `pull_digest_manifest(publish_config.builds_registry, resolved_run_id, ...)`.
- Heading: `f"[Run #{resolved_run_id}]({run_url})"` — already the case.
- Draft anchor: `f"run-{resolved_run_id}"` — already uses run_id.

### 7. verbs/get_app_version.py

- `--run-number` → `--run-id`. Typed `int`.
- `print(f"{base_version}+{run_id}")` — build metadata stamp uses run_id.

### 8. verbs/lint_workflows.py

- `VERB_ARGS`: every `--run-number` regex becomes `--run-id`. Remove duplicate `--run-id` entries (verbs that had both `--run-number` and `--run-id` now have just `--run-id`).
- Update the regex order to match the canonical flag order.

### 9. Tests

- `test_builds.py`: update `matched_ci_run_number` tests to `matched_ci_run`. Change API mock responses from `run_number` to `id`. Update `pull_build_assets`/`pull_digest_manifest` call sites to use `run_id` parameter name.
- `test_prerelease.py`: remove `run_number=42` from `prerelease.main()` calls. Patch `matched_ci_run` instead of `matched_ci_run_number`. The returned value is now `(run_id, html_url)` where `run_id` is the matched integrate run's ID.
- `test_release.py`: change `run_number=42` to `run_id=42`. Add `matched_ci_run` monkeypatch (release now calls it again for the shelf pull).
- `test_draft_releases.py`: remove `run_number=42`, keep `run_id=DRAFT_RUN_ID`. Update `update_pr_draft()` calls.
- `test_get_app_version.py`: change `--run-number` to `--run-id` in CLI invocations.
- `test_lint_workflows.py`: update `PRERELEASE_RUN`, `RELEASE_RUN`, `GET_APP_VERSION_RUN`, and `UPDATE_PR_DRAFT_RUN` (if it exists) constants to use `--run-id` instead of `--run-number`. Remove any `--run-number` entries.

### 10. AGENTS.md

- Invocation grammar: remove all `--run-number` references. Every verb that had `--run-number` now has `--run-id` (some already did — they drop the `--run-number` and keep just `--run-id`).
- Consumption section per-verb: update flag spellings.
- Config section: the `ci_workflow` description mentions "run number" — update to "run id".
- Dev channel section: "keyed by the CI run id" — already says run id, verify consistency.
- Draft release surfaces: asset naming `{stem}-run-{N}.{ext}` — N is now run_id.
- The `matched_ci_run_number` references in the description of `ci_workflow` → `matched_ci_run`, returns run_id.

## Migration order

1. **ci-devkit first** — change `ci-build-unity` to push `run-{github.run_id}` instead of `run-{github.run_number}`. Without this, the shelf tags use the old format and release-devkit pulls won't match.
2. **release-devkit code** — all the changes above.
3. **Consumer workflow YAML** — each consumer repo's `release.yml`, `integrate.yml` update verb invocations to pass `--run-id ${{ github.run_id }}` instead of `--run-number ${{ github.run_number }}`. `lint-workflows` enforces the new contract.
4. **AGENTS.md** — update the documented contract.

## Key invariant after refactor

There is one run identifier: `run_id` (`github.run_id`). It is unique per workflow run across the entire repo. The builds shelf tag is `run-{run_id}`. Dev versions are `-dev.{run_id}`. Build metadata is `+{run_id}`. Draft anchors are `run-{run_id}`. Asset filenames are `{stem}-run-{run_id}.{ext}`. Heading links are `https://github.com/{repo}/actions/runs/{run_id}`. No `run_number` anywhere.

`release`/`prerelease` resolve the integrate run's `run_id` via `matched_ci_run` (API lookup by SHA). `update_pr_draft`/`get_app_version` use their own `github.run_id` directly (they run in `integrate.yml`).
