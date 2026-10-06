# Audit: release-devkit

## Changes applied

- [x] Inline `render_summary` into `render_plan_summary` (plan.py) — also fixes callee-before-caller
- [x] `REGISTRY_URL_BUILDERS` lambdas → format strings (registries.py)
- [x] Inline `actionlint_cache_dir` into `ensure_actionlint` (verbs/lint_workflows.py)
- [x] Extract `setup_publishing_environment` helper into plan.py; verbs/release.py + verbs/prerelease.py call it
- [x] Fold `GitTags` pass-through delegates (`has_changes_since_tag`, `create_and_push_tag`) into class methods
- [x] Delete 3 meta-tests (`test_fake_tag_source_satisfies_protocol`, `test_package_plan_dataclass_shape`, `test_dev_version_formats_cover_every_known_registry`) + 1 redundant `test_render_summary` (subsumed by `test_render_plan_summary`)
- [x] Remove defensive double-call of `ensure_draft_release` inside `append_draft_section` (both callers already ensure)
- [x] Remove unused `sha` parameter from `append_draft_section` signature + update all callers
- [x] Extract `builds.py` from `verbs/create_release.py` — shared utilities (`DigestEntry`, `MatchedRun`, `matched_ci_run_number`, `builds_registry_of`, `pull_build_assets`, `pull_digest_manifest`, `render_images_table`) moved to `builds.py`; `verbs/create_release.py` is now a ~80-line pure verb; `verbs/prerelease.py` and `verbs/update_pr_draft.py` import from `builds` instead of `create_release`
- [x] Inline single-call helpers — `pick_tree_tag` and `ghcr_package_url` inlined into `render_images_table` (builds.py); `select_artifact_file` inlined into `pull_build_assets` (builds.py); `app_has_changes`, `parse_merge_pr`, `existing_dev_builds_digests` inlined into `main` (verbs/prerelease.py); `render_dev_summary` inlined into `main` (verbs/prerelease.py, removed from plan.py). 13 dedicated tests deleted; integration tests cover the inlined logic.
- [x] Extract `drafts.py` from `verbs/draft_releases.py` — same grab-bag smell as the original `create_release.py`. The file was a verb (`update-pr-draft-release`) that was also a shared library for 3 other verbs. `prerelease.py` imported 6 things, `release.py` imported 2, `merge_gate.py` imported 1. Extracted the 9 shared functions + `DEV_DRAFT_TAG` + `_ANCHOR_PATTERN` into top-level `drafts.py`: `stage_draft_assets`, `ensure_draft_release`, `upload_draft_assets`, `delete_draft_release`, `append_draft_section`, `replace_or_prepend_section`, `_parse_sections`, `_join_sections`, `emit_draft_backlink`. The verb file renamed `verbs/draft_releases.py` → `verbs/update_pr_draft.py`, keeps `update_pr_app`, `Settings`, `PR_DRAFT_TAG_PREFIX`, `update_pr_draft`, `build_draft_section`, `emit_draft_summary`. Verb is ~100 lines; `drafts.py` is ~95 lines.
- [x] Fold `create-release` verb into `release` — the verb was dead code: no workflow or consumer ever called it as a standalone CLI; `release.py` was already importing `run_create_release` as a subroutine. Folded `run_create_release` + `collect_build_assets` into `verbs/release.py` as `cut_github_release` + `collect_build_assets`; deleted `verbs/create_release.py`; removed the `create-release` entry point from `pyproject.toml`; renamed `test_create_release.py` → `test_builds.py` (the file only tested `builds.py` functions). Merged `create_release.py`'s `Settings` fields (`github_sha`, `github_actor`, `github_token`) into `release.py`'s `Settings`.
- [ ] Fold `outputs.py` into a shared module — `builds.py` now exists as the natural home
- [ ] Shared `Settings` base class — judgement call on the right factoring
- [ ] `conftest.py` for test helpers — test-only, lower stakes
- [ ] Fix `verbs/prerelease.py:main` ci_step block scope — changes CI output structure
- [ ] `ephemeral_manifest_patch` / `ephemeral_pyproject_patch` skeleton dedup — extraction awkward under no-closures rule
- [ ] `MatchedRun` model simplification — defensible validation of external API response

Verification: ruff check ✅, ruff format ✅, basedpyright 0 errors ✅, 224 tests passed.

---

## Architectural flaws causing line/file bloat

### 1. `verbs/create_release.py` is a shared library masquerading as a verb module — biggest finding [DONE]

`verbs/create_release.py` (was 252 lines, 11 functions/classes) exported **6 shared utilities** consumed by 3 other modules:

| Export | Imported by |
|---|---|
| `DigestEntry` | `verbs/prerelease.py`, `verbs/draft_releases.py` |
| `matched_ci_run_number` | `verbs/prerelease.py` |
| `pull_build_assets` | `verbs/draft_releases.py`, `verbs/prerelease.py` |
| `builds_registry_of` | `verbs/draft_releases.py`, `verbs/prerelease.py` |
| `pull_digest_manifest` | `verbs/draft_releases.py`, `verbs/prerelease.py` |
| `render_images_table` | `verbs/draft_releases.py`, `verbs/prerelease.py` |

The actual verb (`run_create_release`) was 1 of 11 things in the file. The import graph was inverted: `verbs/draft_releases.py` and `verbs/prerelease.py` imported from a "verb" peer, not from a shared library.

**Fix applied:** Extracted the 6 shared utilities + `DigestEntry` + `MatchedRun` into `builds.py`. `verbs/create_release.py` is now a ~80-line pure verb; `builds.py` is a ~170-line focused asset/digest library that all three verbs import from cleanly.

### 2. `verbs/draft_releases.py` is a shared library masquerading as a verb module — same smell [DONE]

`verbs/draft_releases.py` (189 lines) exported **9 shared functions** + `DEV_DRAFT_TAG` consumed by 3 other verb modules:

| Export | Imported by |
|---|---|
| `DEV_DRAFT_TAG` | `verbs/prerelease.py`, `verbs/release.py` |
| `stage_draft_assets` | `verbs/prerelease.py` |
| `ensure_draft_release` | `verbs/prerelease.py` |
| `upload_draft_assets` | `verbs/prerelease.py` |
| `append_draft_section` | `verbs/prerelease.py` |
| `emit_draft_backlink` | `verbs/prerelease.py` |
| `delete_draft_release` | `verbs/release.py`, `verbs/merge_gate.py` |

The actual verb (`update_pr_draft`) was 1 of 14 things in the file. Same inverted-dependency smell as finding #1: `verbs/prerelease.py`, `verbs/release.py`, and `verbs/merge_gate.py` imported from a "verb" peer, not from a shared library.

**Fix applied:** Extracted the 9 shared functions + `DEV_DRAFT_TAG` + `_ANCHOR_PATTERN` into top-level `drafts.py`. The verb file renamed `verbs/draft_releases.py` → `verbs/update_pr_draft.py`, keeping only `update_pr_app`, `Settings`, `PR_DRAFT_TAG_PREFIX`, `update_pr_draft`, `build_draft_section`, `emit_draft_summary`. `drafts.py` is ~95 lines; the verb is ~100 lines. All three consuming verbs now import from `..drafts`.

### 3. `outputs.py` — a 9-line file-per-function [SKIPPED — builds.py now exists as natural home]

One function (`append_line`), 4 lines of logic, 4 callers across 4 modules. This is a file that exists only to hold a single trivial helper. It adds an import and a file to the tree for zero structural benefit.

**Fix:** Fold `append_line` into `builds.py` (or `config.py`, or a `ci_io.py`). Eliminates 1 file. `builds.py` now exists as the natural home.

### 4. Setup block duplicated verbatim between `verbs/release.py` and `verbs/prerelease.py` [DONE]

`verbs/release.py:48-54` and `verbs/prerelease.py:111-117` were character-identical setup blocks.

**Fix applied:** Extracted `setup_publishing_environment(release_plan, packages, workspace)` into `plan.py`. Both verbs call it.

### 5. Six `Settings` classes with overlapping fields [SKIPPED — judgement call on factoring]

Every verb file in `verbs/` defines its own `Settings(BaseSettings)`:

| Field | Files that declare it |
|---|---|
| `github_repository` | release, prerelease, update_pr_draft, merge_gate (4) |
| `github_sha` | release, prerelease, update_pr_draft (3) |
| `github_actor` | release, prerelease, update_pr_draft (3) |
| `github_token` | release, prerelease, update_pr_draft (3) |
| `github_step_summary` | release, prerelease, update_pr_draft, validate_release_plan (4) |
| `github_workspace` | release, prerelease (2) |
| `nuget_api_key` | release, prerelease (2) |

That's ~40 lines of field declarations, many duplicated. A shared base `Settings` (or a single `Settings` with all CI env fields, where each verb reads what it needs) would eliminate the repetition. The per-verb approach means a new env var added to one verb doesn't appear in another's `Settings` — but the overlapping fields are all ambient CI env (`GITHUB_*`), not verb-specific.

### 6. `GitTags` pass-through delegate methods create a dual layer [DONE]

`tags.py` had both module-level functions AND a `GitTags` class whose methods delegated to them.

**Fix applied:** Folded `has_changes_since_tag` and `create_and_push_tag` into `GitTags` as method bodies directly. `list_tag_versions` stays as a module function (called by multiple class methods + monkeypatched in tests).

---

## Inlinable single-call helpers [DONE — all inlined]

Per the inline-single-call-helpers rule (no try block, no idempotency-guard predicate):

| Helper | Was in | Body | Status |
|---|---|---|---|
| `render_summary` | plan.py | 7 lines | **inlined** into `render_plan_summary` (prior pass) |
| `actionlint_cache_dir` | verbs/lint_workflows.py | 1 line | **inlined** into `ensure_actionlint` (prior pass) |
| `pick_tree_tag` | builds.py (was verbs/create_release.py) | 5 lines | **inlined** into `render_images_table` |
| `ghcr_package_url` | builds.py (was verbs/create_release.py) | 9 lines | **inlined** into `render_images_table` |
| `select_artifact_file` | builds.py (was verbs/create_release.py) | 13 lines | **inlined** into `pull_build_assets` |
| `app_has_changes` | verbs/prerelease.py | 4 lines | **inlined** into `main` |
| `parse_merge_pr` | verbs/prerelease.py | 6 lines | **inlined** into `main` |
| `existing_dev_builds_digests` | verbs/prerelease.py | 4 lines | **inlined** into `main` |
| `render_dev_summary` | plan.py | 17 lines | **inlined** into `verbs/prerelease.py:main` (removed from plan.py) |

13 dedicated tests deleted (3 for `pick_tree_tag`, 2 for `ghcr_package_url`, 3 for `app_has_changes`, 2 for `existing_dev_builds_digests`, 2 for `parse_merge_pr`, 1 for `render_dev_summary`). Integration tests cover the inlined logic.

---

## Callee-before-caller violation [DONE — fixed by inlining render_summary]

**`plan.py`**: `render_summary` (callee) appeared **above** `render_plan_summary` (caller). Inlining it into `render_plan_summary` eliminated both the violation and the helper.

All other files follow caller-first ordering correctly.

---

## Guard clauses / catch-and-rethrow

No catch-and-rethrow smells found. The three `try` blocks are all legitimate:
- `NuGetRegistry.publish` (registries.py): catches `CalledProcessError` to **sanitize** the error (strip the API key from the command text before re-raising as `SystemExit`). Specific exception, specific recovery.
- `NpmRegistry.publish` (registries.py): catches `CalledProcessError` to swallow `EPUBLISHCONFLICT` (idempotent re-publish). Specific exception, specific recovery.
- `run_actionlint` (verbs/lint_workflows.py): catches `CalledProcessError` to convert to `SystemExit(returncode)` at the CLI boundary. Top-level boundary pattern.

No guards against impossible scenarios found. The `if not verb_steps: return` early-returns and the `is_mapping`/`is_object_list` TypeGuard checks all guard real conditions.

---

## Code duplication (additional)

### `ephemeral_manifest_patch` / `ephemeral_pyproject_patch` skeleton (registries.py)

Both context managers share the identical read/try/write/yield/finally-restore skeleton; only the patching logic differs (NpmManifest model vs. string replace). Could be a single `ephemeral_patch(path, patch_fn, ...)` with the patching logic passed in — but the no-closures rule means the patch function would need to be a named function, which is what we already have. The skeleton duplication (~8 lines) is real but the extraction is awkward under the constraints.

### Test helper duplication — no `conftest.py`

7 helpers copy-pasted across test files:

| Helper | Files |
|---|---|
| `FixedReturn` | test_builds, test_draft_releases, test_prerelease, test_release (4) |
| `CommandRecorder` | test_get_app_version, test_registries, test_tags (3) |
| `CallRecorder` | test_prerelease, test_release (2) |
| `BashLog` | test_draft_releases, test_merge_gate (2) |
| `null_ci_step` | test_draft_releases, test_merge_gate, test_prerelease, test_release (4) |
| `noop` | test_prerelease, test_release (2) |
| `FakeTags` | test_prerelease, test_release (2) |

A `tests/conftest.py` with shared fixtures would eliminate ~100 lines of test duplication.

---

## Cruft

### `REGISTRY_URL_BUILDERS` — lambdas in a dict (registries.py) [DONE]

Lambdas in a collection — violated the no-closures rule. Replaced with `REGISTRY_URL_TEMPLATES` dict of format strings + `template.format(identity, version)` in `registry_url`.

### Defensive double-call of `ensure_draft_release` [DONE]

`append_draft_section` internally called `ensure_draft_release` again, even though both callers already ensure. Removed the redundant call + the unused `sha` parameter.

### `MatchedRun` model (builds.py)

A pydantic model with two `| None` fields, used once to parse a `gh api --jq` response, followed by `str(parsed.run_number) if parsed and parsed.run_number is not None else ""`. Direct `json.loads` + `dict.get` would be 2 lines. The model adds validation of an external API response — defensible, but the verbosity (`int | None` → `str(...)` → `if not run_number`) is the cost.

### Meta-tests (cruft in the test suite) [DONE — 3 deleted]

- `test_plan.py::test_fake_tag_source_satisfies_protocol` — tests that the test's own fake satisfies a Protocol. Tests the fixture, not production.
- `test_plan.py::test_package_plan_dataclass_shape` — tests that a dataclass constructor assigns `name` to `self.name`. Tests the language.
- `test_registries.py::test_dev_version_formats_cover_every_known_registry` — asserts `set(DEV_VERSION_FORMATS) == KNOWN_REGISTRIES`. Two constants in the same module are equal. Tautological.
- Migration-guard tests for dead schema (`depends_on`, `dependency_pins`, `mirror_prefix` in `test_config.py`; `pr_number not in Settings.model_fields` in `test_merge_gate.py`) — tombstones for removed features. The `feeds` guard is documented (hard flip); the others reject concepts with no live code.

---

## Control-flow smell [SKIPPED — changes CI output structure]

### `verbs/prerelease.py:main` — `ci_step` block too broad, early returns inside it

The `with ci_step("Compute dev publish plan"):` block wraps plan computation, summary rendering, changed-app detection, CI-run lookup, digest pulling, image-change detection, **and** both early returns (nothing-to-publish, dry-run). The step label says "compute plan" but the block does 7 things. The early returns inside the context manager mean `ci_step`'s exit code fires on the early-return path — surprising for a step labeled "compute." The change detection and early-return decisions should be outside the `ci_step`.

---

## Summary of reduction potential

| Change | Status | Lines saved |
|---|---|---|
| Extract `builds.py` from `verbs/create_release.py` | **done** | ~0 net, but 252→~80 for create_release |
| Fold `create-release` verb into `release` | **done** | -1 verb, -1 file, -1 entry point |
| Extract `drafts.py` from `verbs/draft_releases.py` | **done** | ~0 net, but 189→~100 for verb, ~95 in `drafts.py` |
| Fold `outputs.py` into a shared module | skipped | ~5 |
| Inline `render_summary` into `render_plan_summary` | **done** | ~8 |
| Inline `actionlint_cache_dir` into `ensure_actionlint` | **done** | ~3 |
| Inline remaining single-call helpers (7) | **done** | ~40-50 |
| Shared setup helper (release + prerelease) | **done** | ~7 |
| Fold `GitTags` pass-throughs | **done** | ~8 |
| `REGISTRY_URL_BUILDERS` → format strings | **done** | ~5 |
| Remove `ensure_draft_release` double-call + unused `sha` param | **done** | ~5 |
| Delete meta-tests | **done** | ~20 (tests) |
| Shared `Settings` base | skipped | ~25-30 |
| `conftest.py` for test helpers | skipped | ~100 (tests) |
| Fix `verbs/prerelease.py:main` ci_step scope | skipped | — |

Net source lines reduced: ~80 (plus ~40 test lines). All changes verified: ruff, basedpyright, 224 tests passing.
