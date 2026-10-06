# Plan: eliminate the run identifier, unify on SHA

Supersedes `plan.md` (the run_number→run_id unification, partially applied — `matched_ci_run` already returns run id, `--run-id` already dropped from release/prerelease). That refactor asked the wrong question ("which run identifier?"); this one removes the run identifier entirely.

## Problem

`run_id` / `run_number` are **execution identities** masquerading as **content identities**. They key the builds shelf (`run-{N}`), the dev version (`-dev.{N}`), the draft anchor, asset filenames, the build stamp, and the APK `bundleVersionCode` — all of which are properties of *the source tree*, not *the CI run*. The conflation is the root disease: `plan.md`'s run_number-vs-run_id confusion is a symptom (there is no confusion to have if no run identifier is in the contract), and the cross-devkit divergence is already live (unity-devkit and docker-devkit push `run-{github.run_number}`; release-devkit pulls `run-{run_id}` / resolves run id via `matched_ci_run` — mismatched counters).

The SHA is the content identity. Under the **deterministic-builds assumption** (same SHA → same artifact; an explicit invariant this refactor commits to, not a hope), the run adds no content information. The one platform exception is Android `bundleVersionCode`, which requires a monotonically-increasing integer — that becomes a git-derived per-app counter, not a run identifier.

## Decisions (resolved)

1. **Human-readable SHA = 12-char short** (`full[:12]`). The **shelf tag is always the full 40-char SHA** (machine key; push and pull sides must match exactly, no adaptive `--short`).
2. **Clean flip, devkits-first.** No transitional dual-tag. Order: release-devkit (push remote) → unity-devkit + docker-devkit publish SHA-push → each consumer atomic bump.
3. **Dev-build identity = the PR head (P, the certified source)**, not the merge commit (M). release/prerelease resolve `parents[1]` of `--sha` (= M) to get P (the shelf pull needs this anyway); update-pr-draft reads HEAD directly (it runs in integrate, where the checkout IS the PR head). P is also what `get-app-version` stamps (`+{P[:12]}`), so APK stamp, registry dev version, shelf tag, and anchor carry one SHA.
4. **`bundleVersionCode = git rev-list --count HEAD -- {app.path}`** (commits touching the app's source path, reachable from HEAD). Monotonic per app, globally (never resets; grows across releases and reverts), deterministic from SHA+history, git-native. Derived by `get-app-version` (release-devkit owns version derivation; unity-devkit stays a pure stamping door), emitted alongside the version string.

## Invariant after

One content identity: the SHA. Shelf tag = `sha-{full}`. Dev version = `{base}-dev.{short}` (semver) / `{base}.dev{short}` (PEP 440). Build stamp = `{base}+{short}`. Draft anchor = `sha-{short}`. Asset filename = `{stem}-{short}.{ext}`. Heading links to the commit URL. `bundleVersionCode` = the per-app commit count (the one non-SHA value — a platform-mandated integer). No `run_id`, no `run_number`, no `matched_ci_run`, no `ci_workflow` config field, no `actions: read` for a run lookup, anywhere.

## release-devkit changes (home repo)

Pre-step: the working tree has uncommitted cosmetic diffs on `prerelease.py` / `release.py` / `update_pr_draft.py` (the prior refactor's tail — hoisting, `packages`→`publish_config.packages`). Commit or discard before starting.

### `builds.py`
- **Delete** `matched_ci_run` (lines 31-47) and `MatchedRun` (lines 26-28). The `gh api …/actions/workflows/{ci_workflow}/runs?head_sha=…` query, the `actions: read` dependency, and the "No successful CI run found" path all go.
- **Add** `certified_sha(sha: str) -> str` — resolves the PR head from a merge commit via one local git call (no API, no token):
  ```python
  def certified_sha(sha: str) -> str:
      parents = bash_output(f"git log -1 --format=%P {sha}").strip().split()
      return parents[1] if len(parents) >= 2 else sha
  ```
  Returns the full 40-char SHA. Used by release/prerelease (full clone; M is fetched). Fallback to `sha` for non-merge commits (defensive; evergreen makes every dev/main commit a merge).
- `pull_build_assets` / `pull_digest_manifest`: rename param `run_id` → `sha`; `build_tag = f"sha-{sha}"` / `tag = f"sha-{sha}"` (full SHA).

### `drafts.py`
- `publish_draft_assets`: rename `run_id` → `build_sha` (the certified full SHA); keep `sha` → `target_sha` (the `--sha`, for `gh release create --target`). Asset name `f"{stem}-run-{run_id}{suffix}"` → `f"{stem}-{build_sha[:12]}{suffix}"` (drop the `-run-` infix; the short SHA is self-identifying). `pull_build_assets(config, build_sha, …)`.

### `publishing.py`
- `DevStrategy.__init__(run_id)` → `DevStrategy(build_sha)`; `self._run_id` → `self._build_sha`. The dev version token passed in is the **short** SHA (`certified[:12]`).

### `registries.py`
- `semver_dev_version(base, run_id)` → `semver_dev_version(base, short_sha)`; body `f"{base}-dev.{short_sha}"`.
- `pep440_dev_version(base, run_id)` → `pep440_dev_version(base, short_sha)`; body `f"{base}.dev{short_sha}"`.

### `config.py`
- **Delete** `ci_workflow: str` (line 48). With `matched_ci_run` gone it has no consumer. `extra="forbid"` makes this a hard cutover: every consumer's `release-devkit.yaml` must drop the `ci_workflow` key in the same commit that bumps the pin.

### `verbs/get_app_version.py`
- Drop `--run-id`. Flags: `--app <name>` only.
- Read HEAD: `head = bash_output("git rev-parse HEAD").strip()` (full). Compute `count = int(bash_output(f"git rev-list --count HEAD -- {app_config.path}").strip())`.
- Emit **two** `$GITHUB_OUTPUT` lines (write to `os.environ["GITHUB_OUTPUT"]` if set; else print to stdout for local use — the lint regex excludes `"` from verb args, so a `>> "$GITHUB_OUTPUT"` redirect in the step is not viable; write-direct matches the existing `id: version` step shape):
  ```
  version={base_version}+{head[:12]}
  version-code={count}
  ```
  `base_version` is the existing `next_version(...)` derivation (unchanged). `app_config.path` is already on the loaded config.

### `verbs/release.py`
- `matched_run_id, _ = matched_ci_run(repository, sha, publish_config.ci_workflow)` → `certified = certified_sha(sha)`.
- `pull_digest_manifest(publish_config.builds_registry, certified, …)`; `pull_build_assets(publish_config, certified, …)`. (Shelf tag is now `sha-{certified}` full.)

### `verbs/prerelease.py`
- `matched_run_id, html_url = matched_ci_run(...)` → `certified = certified_sha(sha)`; `commit_url = f"https://github.com/{repository}/commit/{certified}"`; `short = certified[:12]`.
- `pull_digest_manifest(..., certified, …)`.
- `DevStrategy(matched_run_id)` → `DevStrategy(short)`.
- `publish_draft_assets(draft_config, certified, actor, token, DEV_DRAFT_TAG, repository, sha)` (`certified` = build_sha, `sha` = target_sha).
- Heading: replace `[Integrate run #{matched_run_id}]({html_url})` with `[{short}]({commit_url})` (the PR link fragment below it is unchanged).
- Anchor: `f"run-{matched_run_id}"` → `f"sha-{short}"`.

### `verbs/update_pr_draft.py`
- Drop `--run-id`. The certified SHA is **HEAD** (this verb runs in integrate.yml, where the checkout is the PR head P — M is not fetched and must not be resolved here): `certified = bash_output("git rev-parse HEAD").strip()`; `short = certified[:12]`; `commit_url = f"https://github.com/{repository}/commit/{certified}"`.
- `pull_digest_manifest(..., certified, …)`.
- `publish_draft_assets(publish_config, certified, actor, token, tag, repository, sha)` (`sha` = `--sha`, the draft target).
- Heading: replace `[Run #{resolved_run_id}]({run_url})` with `[{short}]({commit_url})`.
- Anchor: `f"run-{resolved_run_id}"` → `f"sha-{short}"`.
- `--sha` stays (used for the draft release `--target`).

### `verbs/lint_workflows.py`
- `VERB_ARGS["get-app-version"]`: `r"^ --app \S+$"` (drop `--run-id`; no redirect — output is write-direct).
- `VERB_ARGS["update-pr-draft-release"]`: `r"^ --pr-number .+ --repository .+ --sha .+ --actor .+ --step-summary .+$"` (drop `--run-id`).
- `release` / `prerelease` / `merge-gate` / `validate-release-plan` / `lint-workflows` regexes: unchanged.
- (Optional, not blocking: lint does not currently enforce the validate-release-plan job `outputs:` block or per-job `permissions:`. The `version-code` output wiring and the `actions: read` drop are consumer-template changes, enforced by review + the verb-args regex, not by a new lint rule.)

### Tests (release-devkit)
- `test_builds.py`: delete the `matched_ci_run` tests; add `certified_sha` tests (merge commit → second parent; non-merge → self). Update `pull_build_assets`/`pull_digest_manifest` call sites to `sha=`. Drop the `run_result_json` helper.
- `test_get_app_version.py`: drop `--run-id` from invocations; assert the two emitted lines (`version=…+<short>`, `version-code=<count>`); mock `git rev-parse HEAD` + `git rev-list --count`.
- `test_prerelease.py` / `test_release.py`: drop the `matched_ci_run` monkeypatch; patch `certified_sha` (or mock `git log -1 --format=%P`); assert dev versions / anchors / shelf tags use the short/full SHA.
- `test_draft_releases.py`: drop `run_id=`; pass `build_sha=` (certified) + `target_sha=`; assert asset names `{stem}-{short}` and anchors `sha-{short}`.
- `test_lint_workflows.py`: update `get-app-version` / `update-pr-draft-release` fixtures to the new arg shapes; audit the `--run-number … --branch` fixtures (lines ~426/459/473 — confirm they are run-step-fold test fixtures, not verb contracts, and update any stale `--run-id`/`--run-number` references).

### `AGENTS.md` (release-devkit)
Rewrite every run-id reference: the `prerelease`/`release` verb rows (drop "resolved internally via `matched_ci_run`"; the shelf is pulled by `sha-{certified}` resolved from `--sha`), the `get-app-version` row (drop `--run-id`; emits `version` + `version-code`), the `update-pr-draft-release` row (drop `--run-id`), the invocation-grammar block, the Dev channel section ("keyed by the certified SHA"), the Draft release surfaces section (`sha-{short}` anchors, `{stem}-{short}` asset names), the Config section (`ci_workflow` deleted — remove its description), and the `actions: read` mentions in the `prerelease`/`release` job descriptions.

## unity-devkit changes (push side + stamping)

### `ci_build_unity.py`
- Drop `--run-number`. Add `--version-code: Annotated[int, typer.Option(help="Android bundleVersionCode (the per-app commit count from get-app-version)")]`.
- Shelf tag: `tags = (derived_cache_key, f"run-{run_number}")` → `tags = (derived_cache_key, f"sha-{bash_output('git rev-parse HEAD').strip()}")` (full SHA; read HEAD, no flag). `derived_cache_key` (PR-number-based) is **unchanged** — out of scope.
- `build_player(..., run_number=run_number, …)` → `build_player(..., version_code=version_code, …)`.

### `build_unity.py` (local build verb)
- `--run-number` → `--version-code` (same rename; defaults to 0 for local unversioned builds).

### `player_build.py`
- `build_player(..., run_number: int = 0, …)`: rename `run_number` → `version_code`.
- Stamping (line 223): `("AndroidBundleVersionCode", str(run_number))` → `("AndroidBundleVersionCode", str(version_code))`; update the log line likewise.

### `install.py`
- `--run N` (pull `:run-N`) → `--sha <sha>` (pull `:sha-{sha}`). Line 113: `tag = f"run-{run}" if run else cache_key(...)` → `tag = f"sha-{sha}" if sha else cache_key(...)`. `--pr-number` and the default dev-cache-key path are unchanged (PR-number-based, out of scope).

### `identity.py`
- No change. `cache_key` is PR-number-based (`{name}-{platform}-pr-{N}` / `-dev`), not a run identifier.

### unity-devkit tests + `AGENTS.md`
- `test_build_player.py`: `run_number=42` → `version_code=42` (and the `0.2.7-dev+42` fixtures — the `+42` is a build-metadata stamp, keep as a value but the param name changes).
- `AGENTS.md`: rewrite the `ci-build-unity` row (drop `--run-number`; `--version-code`; shelf tag `sha-{full}`), the `build-unity` row, the `install` row (`--sha`), and the "N is `github.run_number`, not the Actions run ID" notes (gone). The build-outputs section's `run-{N}` → `sha-{full}`.

## docker-devkit changes (digest shelf push side)

### `build_docker.py`
- `--run-number` (line 73-75) → `--sha: Annotated[str, typer.Option(help="CI head SHA baked into the digest manifest's builds-shelf tag")]`.
- `run_build(..., run_number: int = 0)` → `run_build(..., sha: str = "")`; `push_image_digests(builds_registry, run_number, …)` → `push_image_digests(builds_registry, sha, …)`.
- `push_image_digests`: replace `if run_number <= 0: raise …` with `if not sha: raise typer.BadParameter("--builds-registry requires --sha")`. Tag `f"run-{run_number}"` → `f"sha-{sha}"` (full SHA — the workflow passes `github.event.pull_request.head.sha`).
- `test_build_docker.py`: `test_push_image_digests_rejects_zero_run_number` → `…_rejects_empty_sha`.

### docker-devkit `AGENTS.md`
- The ci-devkit-edge paragraph: "`--builds-registry` + `--run-number`" → "`--builds-registry` + `--sha`"; "`run-{N}`" → "`sha-{full}`".

## ci-devkit

**No code change.** `push_build` / `pull_build` / `build_exists` / `build_reference` take a plain `tag: str` (verified — `ci-devkit/src/ci_devkit/builds.py`). The caller composes the tag; ci-devkit is the clean floor and survives any tag scheme.

## Consumer workflow + config template (every consumer repo)

Each consumer's atomic bump commit touches:

### `release-devkit.yaml`
- Delete the `ci_workflow:` line (hard requirement — `extra="forbid"` fails load otherwise).

### `.github/actions/setup-release-devkit/action.yml`
- Bump `RELEASE_DEVKIT_COMMIT` to the release-devkit SHA that has the SHA-pull code (must exist on the remote first — release-devkit pushes before any consumer bumps).

### `uv.lock`
- Bump unity-devkit and docker-devkit to the published versions carrying the SHA-push code (app/image repos only; pure-Python repos bump only if they invoke `build`).

### `.github/workflows/integrate.yml`
- **`validate-release-plan` job**: `get-app-version --app X` step keeps `id: version` (no redirect — write-direct). Add `version-code` to the job `outputs:` block: `version-code: ${{ steps.version.outputs.version-code }}` (beside the existing `version:`).
- **`build-unity` job** (app repos): `ci-build-unity` step — drop `--run-number ${{ github.run_number }}`, add `--version-code ${{ needs.validate-release-plan.outputs.version-code }}`. `--version` source unchanged (`needs.validate-release-plan.outputs.version`).
- **`build` / `build-zed` job** (image repos): drop `--run-number ${{ github.run_number }}`, add `--sha ${{ github.event.pull_request.head.sha }}`.
- **`update-pr-draft-release` step**: drop `--run-number`/`--run-id`; spell the full target contract `--pr-number … --repository … --sha ${{ github.sha }} --actor … --step-summary …` (capture-tool/Make-it-Sing currently carry a stale partial invocation — bring to the full contract).

### `.github/workflows/release.yml`
- `prerelease` and `release` jobs: drop `actions: read` from `permissions:` (no more `matched_ci_run` API query). The verb invocation lines are unchanged (already `--repository --sha --actor --workspace --step-summary`-less bare invocations on most consumers — they resolve to the explicit-flag contract via the pin bump; verify each consumer's step spells the full flag set the lint now requires).

## Migration order (clean flip, devkits-first)

1. **release-devkit** — implement all changes above; push the branch to the remote (the SHA must exist before any consumer can pin it). This repo has no `release.yml` of its own (published nowhere), so its own `integrate.yml` self-test is the only local validation.
2. **unity-devkit** — implement the SHA-push + `--version-code` changes; bump its own `setup-release-devkit` pin to step-1's SHA; drop `ci_workflow` from its `release-devkit.yaml`; update its workflows. Publish a new unity-devkit version to PyPI.
3. **docker-devkit** — implement the `--sha` digest-push change; bump its release-devkit pin; drop `ci_workflow`; update workflows. Publish.
4. **Each remaining consumer** (placeframe, placeframe-capture-tool, Make-it-Sing ×2, lbe-toolkit, bashrun, ci-devkit, logger-conf, Nessle, ObserveThing, pydantic-settings-pulumi, python-devkit) — one atomic commit: bump `uv.lock` (unity/docker where relevant) + bump release-devkit pin + drop `ci_workflow` + update `integrate.yml`/`release.yml`. lint-workflows (new contract) enforces the verb shapes.

Within a consumer, the bump is self-consistent (new push-side deps + new release-devkit pin both use `sha-{…}`). An incomplete bump (new push dep, old release-devkit pin) 404s at the first dev prerelease — caught immediately, no silent corruption.

## Outliers (reconcile or exclude before/step-4)

- **openapi-client-codegen**: still invokes `publish-prerelease` (the dead pre-rename name). It must move to `prerelease` with the full SHA contract as part of its bump, or be excluded from publishing until reconciled.
- **StatefulUnity**: has a non-standard `--run-id ${{ github.event.workflow_run.id }}` "Publish dev prereleases" flow (a `workflow_run`-triggered delivery path, which violates the org-wide delivery-bridge ban). Audit separately — it is not on the standard three-workflow contract and cannot be batch-bumped; it needs its own reconciliation to the standard contract or an explicit exemption.

## Orphans / cleanup

- Old `run-{N}` shelf tags on ghcr (build outputs + digest manifests) become orphaned. ghcr Container-registry storage is separately free (does not count against the Actions+Packages quota), so leaving them is harmless. Optional: a one-off `oras delete` sweep per repo after migration. Not blocking.
- `plan.md` is superseded by this file; delete on a separate prose commit once the refactor lands.

## Deterministic-builds precondition

The whole design rests on same-SHA → same-artifact. Unity APK builds and Docker layers are not reproducible by default; this refactor commits to making them so (build-metadata stamping already moves toward content-addressing via the digest manifest). Until reproducibility holds, a re-run of integrate on an already-landed SHA could push a different artifact under the same `sha-{head}` tag, and a release pulling it would staple an untested rebuild. The mitigation is reproducible builds, not reintroducing a run identifier.
