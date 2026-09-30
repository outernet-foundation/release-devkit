# release-devkit

## What this is

The publication machinery for outernet-foundation repos: the publish pipeline, the per-package tag ledger and path-diff change detection, ephemeral version patching, manifest-inferred dependency edges, and release orchestration. A standalone repo (sibling of `unity-devkit` / `docker-devkit` / `bashrun`), **published nowhere and versioned not at all**: it is consumed exclusively as a git checkout at a pinned commit SHA, through the composite actions under `.github/actions/`. It must stay a project dependency of nothing (the reason is structural: every tool repo it publishes sits inside its own dependency graph — bashrun and ci-devkit are release-devkit's runtime deps — so a project-level release-devkit edge in those repos is a resolver cycle plus a root-version conflict against the committed version sentinel), and the checkout is the seal: the whole dependency closure resolves from the checkout's committed `uv.lock` (`uv sync --locked --no-dev`), exactly like every other devkit consumption in the org — no run-time float, no published artifact to drift from its lock.

The consumer owns everything declarative: package and app identities, paths, registry mappings, and the builds shelf each app's release assets pull from live in a consumer-authored `release-devkit.yaml` at the repo root; every command here reads that file. Per-repo copies of this machinery are refused, as are per-ecosystem splits — the seam is internal: one `Registry` adapter per registry over the shared ledger/diff/versioning core.

The package is `release-devkit` (src-layout under `src/release_devkit/`; import `release_devkit`). Runtime dependencies: `bashrun` (all shell-outs), `ci-devkit` (`ci_step`, runner setup, `builds` — release-asset pulls), `pydantic`/`pydantic-settings` (config + CI env), `strictyaml` (config loading), `typer` (CLIs) — all from PyPI, zero domain dependencies. First-party dependencies are exact-pinned (`bashrun==`, `ci-devkit==`) so any fresh resolve is deterministic; the committed lock is the consumption contract.

Each job needing release logic checks this repo out at a full commit SHA — a workflow-level `RELEASE_DEVKIT_SHA` env pin (never a branch or tag; a movable ref reintroduces version float) — into `.release-devkit/` beside the consumer's own checkout, then invokes a local composite action: `uses: ./.release-devkit/.github/actions/<verb>`. The action syncs its own venv from the checkout's lock (`uv sync --locked --no-dev`) and executes the verb against the consumer workspace, so the glue (`action.yml`) and the tool are the same checkout at the same SHA — they cannot diverge. The action self-serves the env it knows it needs (`GH_TOKEN`, `CI_REGISTRY_USERNAME`/`CI_REGISTRY_TOKEN`, `NPM_CONFIG_LOGLEVEL`); the consumer's job owns only `permissions:` and `environment:`.

An inline `run:` step executes in the caller's job, so `job_workflow_ref` resolves to the **caller's** workflow file: the OIDC trusted-publishing identity is the caller's own, which is the property PyPI hard-requires (warehouse#11096 blocks reusable-workflow publishers) and npm binds (the caller's top-level workflow filename). Inline steps and composite actions are OIDC-safe; reusable workflows are not — the publish jobs must never be converted to one. The composite actions preserve this property: their steps execute inside the caller's job, no differently from an inline step.

## Consumption model (no publication)

Nothing is ever published from this repo — no PyPI wheel/sdist, no Release assets, no `release-devkit-v*` tags. The commit history is the changelog, and consumers pin by full commit SHA; "what changed since our pin" is `git log <old>..<new>`. There is no version ledger for the tool itself (the ledger machinery serves consumers' own packages). Its own `ci-cd.yml` is `check`-only (dev/PR gated, nothing runs on `main`): `preflight-python` plus a self-test that invokes `./.github/actions/publish-stable` with `dry-run: true` — the local-action path is identical to consumer invocation because `github.action_path` sits three levels below the repo root in both layouts, so the self-test exercises the exact composite consumers run. The committed `pyproject.toml` version is permanently the `0.0.0.dev0` sentinel. Bumping a consumer means changing one env line; the pinned SHA must exist on the remote before consumer CI runs, so this repo's branch is always pushed first.

## Commands

One console script per verb (`app-build-version`, `publish-stable`, `publish-dev`, `create-release`, `ensure-release-pr`; the workflow contract: script names and flags are the public API). The composite actions invoke them from the action's own synced venv; humans can run `uv run <verb>` from a checkout. Config defaults to `release-devkit.yaml` where optional.

| Command | Role |
|---|---|
| `app-build-version` | Print the version a CI build of an app should stamp: `{next_version}+{run}` — `next_version` derived from the app's declared `major_minor` and the `{name}-v*` tag ledger (prerelease-suffixed tags excluded; no in-line tag → `{major_minor}.0`), the same `next_version` `publish-stable` uses to tag the release so the build-time stamp matches the eventual release tag. Run number from `--run-number` or the ambient CI run number. The build-time half of the versioning boundary: this tool owns version derivation, build tools own stamping, and the consumer's workflow bridges the two — the emitted string is opaque to the build door that receives it. |
| `publish-stable` | Compute the publish plan from the tag ledger + path-diff, publish every changed package to its registries, bump and tag app versions, push per-package tags, then cut the GitHub Release (`create-release` runs internally whenever something published — there is no `published` output and no separate gated step). `--dry-run` prints the plan and runs every plan-time validation without publishing. |
| `publish-dev` | Dev-channel mode: publish immutable `-dev.<run-id>` prereleases of every path-diff-changed package to its registries. `--run-id` defaults to the ambient CI run id; never creates git tags, never touches app versions. |
| `create-release` | Assemble release notes (package versions with registry links, app versions), pull each app's build artifacts from its builds shelf (`pull_build` at the matched CI run), and cut the CalVer-named (`YYYY.MM.N`, counting releases within the month) GitHub Release with those assets. `publish-stable` calls it internally on every real publish; as a standalone verb it exists for manual re-creates. |
| `ensure-release-pr` | Maintain the standing `dev` → `main` "Next release" gate PR. |

One composite action per verb under `.github/actions/<verb>/action.yml` (`publish-stable`, `publish-dev`, `ensure-release-pr`, `app-build-version`; `create-release` stays a manual CLI verb — it always runs inside `publish-stable`, so no workflow calls it directly). Each action owns its consumer checkout with the verb's defaults and takes a `checkout` input (default true) so `check` jobs — which already hold a ledger-shaped checkout — can pass `checkout: false` instead of paying a second full clone. `app-build-version` exposes the stamped version as an output; `publish-stable` takes `dry-run` and `with-apps` inputs.

## Consumption shape

Every consumer runs one workflow file, `ci-cd.yml`, combining CI and release. Triggers: `workflow_dispatch`, `push: [main, dev]`, `pull_request: [dev]` — never `workflow_run` (it was only ever the bridge between two files; one file means `needs` is the green gate) and never `pull_request: [main]`: the standing release PR's head is the dev tip that just ran identical CI via the push event, so letting it fire doubles CI (including the QEMU matrices) on every dev push. Consequence: the release PR reports zero checks; `main`'s branch protection must require no status checks. Exactly one workflow-level concurrency block and zero per-job blocks:

```yaml
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}
```

Superseded runs on the same branch cancel whole; `main` runs queue instead — and `publish-stable`, the one job that must never die mid-release, is only reachable from `main`, where cancel is off (the queue is the publish mutex). A cancelled dev publish is safe by construction: `-dev.<run-id>` prereleases are immutable, create no tags, and the successor run re-points the npm `dev` dist-tag; killing a stale run also kills its `ensure-release-pr` bot tick, which removes the duplicate-PR race. CI jobs (`check`, `mirror`, builds) are gated `if: github.ref != 'refs/heads/main'`; `publish-stable` runs `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`; `publish-dev` and `ensure-release-pr` run on `dev` push.

The needs-chain law: `check` is the root; `publish-dev` needs the DAG sinks of the repo's build jobs; `needs` is transitive, so ancestors are never re-listed. The one sanctioned deviation: a `mirror` job may run as the parallel root ahead of `check` — mirror is a near-always no-op (existence probes; only changed entries copy), so serializing it behind `check` buys nothing, and when `check` itself consumes mirror-prefixed images (placeframe's postgres-wrapper preflight build) the inversion is forced anyway. Chaining expensive builds behind `check` matters because `check`'s trailing dry-run fails a broken `release-devkit.yaml` at minute 3 instead of after a 40-minute build that could never ship.

Every verb-owning job starts with a job-level checkout of this repo (public, no token needed): `actions/checkout@v5` with `repository: outernet-foundation/release-devkit`, `ref: ${{ env.RELEASE_DEVKIT_SHA }}`, `path: .release-devkit`, `persist-credentials: false` — followed by `uses: ./.release-devkit/.github/actions/<verb>`. The action's internal consumer checkout runs `clean: false` (the default clean would evict the `.release-devkit` housemate) with the verb's ledger shape: `fetch-depth: 0` + `fetch-tags: true` (`fetch-tags` is broken with shallow clones), `persist-credentials: false` everywhere except a real `publish-stable`, whose credentials must persist for the tag push:

- `check` (every repo) — ledger checkout + setup-uv + the python battery, then the release-devkit checkout, `app-build-version` (app repos; `checkout: false`, version exported as a job output for the build workflow — no separate `resolve-version` job) and `publish-stable` dry-run (`checkout: false`) as the trailing step (the publish-plan gate).
- `ensure-release-pr` — release-devkit checkout + action, **no `needs`**: it consumes no CI output, and a standing PR tracking a red dev branch is the accurate state.
- `publish-stable` — release-devkit checkout + action (`ref: main` checkout with persisting credentials happens inside the action). Consumer job keeps `environment: release`, permissions `contents: write` + `id-token: write` (+ `packages: write`, `actions: read` where apps pull the builds shelf or the matched-CI-run lookup queries the Actions API), and any registry-secret env it alone knows (`NUGET_API_KEY` — job env flows into the action's steps). The GitHub Release is cut inside the command — no separate `create-release` step.
- `publish-dev` — a normal job in the dev-push run, not a `workflow_run` follow-up: release-devkit checkout + action with no `--run-id` (the ambient CI run id is the correct number). No tags, no releases.

## The CI-commit-free invariants

CI and release workflows must not create commits on any branch — `dev` → `main` merges are always true fast-forwards. The machinery that makes that possible lives here:

- **Version tracking**: per-package git tags (`{name}-v{semver}`, e.g. `placeframe-api-client-v0.1.8`, `capture-tool-v0.2.0`), never committed state files. The git-tag ledger primitives (`list_tag_versions`, `has_changes_since_tag`, `create_and_push_tag`) live in `ledger.py` here — version-ledger semantics are this repo's concern; ci-devkit is the GHA runner floor.
- **Change detection**: `git diff --quiet <last-tag> HEAD -- <path>`, never content hashing. No cascade: an unchanged dependent is an immutable, coherent pairing — consumers adopt newer siblings through their own pins (UPM/npm treat declared dependency values as minimums, so a newer sibling always satisfies).
- **Version scheme**: the major.minor is config data, the patch is ledger data. Every package and app entry declares a required `major_minor` string (`"M.m"`); the planned version is the highest stable tag within that line plus one patch, or `.0` when the line has no tags — a first release is whatever the declared line says. A declared line below any existing ledger version fails loudly (never compute downward). Per-package numbers are independent within one release event — no lockstep.
- **Manifest version sentinels**: Unity `package.json` versions are permanently `0.0.0+local` in the repo; patched ephemerally during `npm publish` and restored immediately — never committed. Python `pyproject.toml` versions are permanently `0.0.0.dev0` in the repo; patched ephemerally around `uv build` and restored immediately. The sdist/wheel carries the real version; the committed file never does.

## The dependency-edge law

Same-release-unit dependency edges are **inferred from manifests**, not authored in config: each package's manifest dependencies (package.json `dependencies` for npm, `[project].dependencies` for pypi, csproj `PackageReference` for nuget) are intersected with the config's registry identities; a match is an edge, everything else is an external dependency that ships verbatim. Edges drive topological plan ordering — dependencies-first, load-bearing for nuget, where `dotnet pack` restores the sibling from the registry — and validation only, never version selection.

Same-unit dependencies are authored as the sentinel `0.0.0+local` — one string that is valid semver (build metadata), PEP 440 (local version), and NuGet. The concrete version exists only in the published artifact, injected at publish from the event's ledger: the sibling's new version if it co-publishes, its current tag if unchanged (HEAD is then byte-identical to that release), and a loud error if it never published. The dev channel injects a co-publishing sibling's `-dev.<run-id>` spelling and an unchanged sibling's current stable tag. Cross-unit and ecosystem dependencies are authored exact and shipped verbatim — adoption is a human commit.

Plan-time validations, all atomic before any registry call, all caught by `--dry-run`: a sentinel on a non-config identity; a real version where a config identity expects the sentinel (hard flip — staleness cannot ship); a sibling that has never published; cyclic edges.

### Reference regimes (how same-unit dependencies are wired on disk)

| Regime | Local | Publish |
|---|---|---|
| Unity sibling, same project | asmdef assembly-name references | package.json sentinel, ephemeral patch |
| Same repo, outside the consuming project | `file:` path in the project's Packages/manifest.json + asmdef name | package.json sentinel, ephemeral patch |
| Cross-repo (lbe-toolkit → placeframe) | exact registry pin in the consumer's project manifest | the same adopted pin, verbatim |
| Ecosystem deps (UniTask, org.nuget.*) | authored exact | verbatim |
| nuget sibling | ProjectReference (version-free) | `PackageReference Version="$(Prop)"` with the property defaulting to `0.0.0+local`; injected via `-p:<Prop>=<version>` beside `-p:Version` |
| pypi sibling | `[tool.uv.sources]` workspace override | `name==0.0.0+local`, specifier patched ephemerally |

## Release units

The repo is the release unit: repos release independently; one release event publishes every changed package in the repo together; a package unchanged since its last tag is skipped (registries are immutable — there is nothing to publish), and dependents are never republished for a sibling's change.

## Dev channel

`publish-dev` publishes immutable prereleases of every path-diff-changed package; it creates no git tags, bumps no app versions, and opens no release. Versions are keyed by the CI run id and spelled per registry — `{base}-dev.{run_id}` where semver allows it (nuget, npm), `{base}.dev{run_id}` on PyPI — because no single string is both valid semver and valid PEP 440. The base is the next version derived from the declared `major_minor` and the tag ledger, so a package's dev versions share one base until the stable flow tags it. npm prereleases ride the single inert `dev` dist-tag so `latest` never moves. The job prints the exact published versions; that print is the consumption interface — consumers pin by hand, there is no discovery tooling.

## The Registry seam

`registries.Registry` is the registry adapter protocol (`publish(request: PublishRequest)`); `NuGetRegistry`, `NpmRegistry`, and `PyPIRegistry` implement it. A registry's identity (nuget package id, npm name, PyPI distribution name) is config data, not code — the same package can publish to several registries at one version. Config-declared registry names are validated against `registries.KNOWN_REGISTRIES` at load time.

`PyPIRegistry` shells out to `uv build` + `uv publish` and authenticates via trusted publishing (OIDC): it takes no credential, so the consuming workflow needs `id-token: write` and the PyPI project needs a configured (or pending) publisher for that repo/workflow. Idempotent re-publishing is handled by `uv publish --check-url` against the simple index. npm authenticates the same way — trusted publishing via `--provenance`, no token plumbing — and npm allows one trusted publisher per package, bound to a single workflow filename: every workflow that publishes a given package to npm must be the same file.

## Config

`config.PublishConfig` (pydantic, loaded by `load_config`) validates the consumer's root `release-devkit.yaml`. The config-file law org-wide (home: this file; siblings reference it, they don't duplicate it): config lives beside the unit whose facts it carries; consumption model and config location are independent axes. A tool whose subject is the Python project configures from pyproject `[tool.<devkit>.*]` tables (the black/ruff pattern); every other devkit configures via one root `<devkit>.yaml` per repo. python-devkit is the one pyproject-table devkit (its subject is the Python workspace); unity-devkit is the one JSON exception (its config is read by C# inside Unity, which ships no YAML parser). release-devkit / openapi-client-codegen / docker-devkit are root `.yaml`. Strict loading: strictyaml rejects duplicate keys and preserves all scalars as strings (no implicit typing — unquoted `0.1` stays `"0.1"`); pydantic coerces per-field from the string-preserving parse with `extra="forbid"` on every model.

- The registry-mapping key is `registries`. Hard flip, no accept-both: unknown keys are rejected (`extra="forbid"`), so an unmigrated config fails loudly at load instead of silently publishing with zero registries.
- `ci_workflow` is required: it is the matched-CI-run lookup key (`gh api …/workflows/{name}/runs?head_sha=…`) that disambiguates whose build artifacts a release staples — several workflows run on the release SHA, including Release itself, so a `"ci.yml"` default would be silently wrong for repos whose CI file is named differently. The lookup resolves the merge commit's second parent (the dev tip that ran CI) and yields that run's **run number**, which is the `run-{N}` tag every builds shelf carries.
- An app entry may declare a `builds` shelf: `registry` (the builds namespace, e.g. `ghcr.io/{owner}/{repo}/builds`) plus an `artifacts` list whose entries carry `project` and `platform` — composed through ci-devkit's `build_reference`, so the pull side cannot drift from whatever pushed the shelf. `project`/`platform` must be the push side's exact spelling (the Unity project name and platform for APKs; docker-devkit's lock convention for image locks), never the app/tag-prefix name. Optional `file` selects which pulled layer becomes the asset when a build pushes several (APK builds also push `BuildReport.json`); optional `name` renames the asset on the release (e.g. `CaptureTool-AndroidMobile.apk`). Apps without a `builds` section release with no stapled build assets.
- The mapping fields (`packages`, `apps`) may be omitted when empty — an apps-only repo declares no `packages` key at all. Both key packages and apps by name, which doubles as the git-tag prefix (`{name}-v{semver}`); apps carry no separate `display_name` or `tag_prefix`. There is no `requires` field and no config-level version check: the workflow's `RELEASE_DEVKIT_SHA` pin is the only version control, and a config cannot meaningfully constrain a tool whose version is a commit hash.

## See also

- `README.md` — human-facing usage and consumption wiring.
- [`bashrun`](https://github.com/outernet-foundation/bashrun) — the subprocess wrapper every shell-out goes through.
