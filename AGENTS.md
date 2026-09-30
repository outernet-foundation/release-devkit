# release-devkit

## What this is

The publication machinery for outernet-foundation repos: the publish pipeline, the per-package tag ledger and path-diff change detection, ephemeral version patching, manifest-inferred dependency edges, and release orchestration. A standalone repo (sibling of `unity-devkit` / `docker-devkit` / `bashrun`), published to PyPI and consumed **uvx-isolated** — it is a project dependency of nothing. The reason is structural: every tool repo it publishes sits inside its own dependency graph (bashrun and ci-devkit are release-devkit's runtime deps), so a project-level release-devkit edge in those repos is a resolver cycle plus a root-version conflict against the committed version sentinel.

The consumer owns everything declarative: package and app identities, paths, and registry mappings live in a consumer-authored `release-devkit.yaml` at the repo root; every command here reads that file. Per-repo copies of this machinery are refused, as are per-ecosystem splits — the seam is internal: one `Registry` adapter per registry over the shared ledger/diff/versioning core.

The package is `release-devkit` (src-layout under `src/release_devkit/`; import `release_devkit`). Runtime dependencies: `bashrun` (all shell-outs), `ci-devkit` (`ci_step`, runner setup), `packaging` (PEP 440 specifier parsing for `requires`), `pydantic`/`pydantic-settings` (config + CI env), `strictyaml` (config loading), `typer` (CLIs) — all from PyPI, zero domain dependencies.

Consumers invoke `uvx --from release-devkit==${{ env.RELEASE_DEVKIT_VERSION }} <command>` in plain `run:` steps of their own publish jobs — the version is a published, changelogged PyPI version pinned in the consumer's workflow `env:` (`RELEASE_DEVKIT_VERSION`, bumped manually and independently of other devkits). No composites, no bootstrap action, no vendored checkout, no git-SHA pin: a SHA is less scrutable than a released version (it can point at any commit and maps to no changelog), and the rare need to test an unpublished release-devkit change is handled ad hoc — temporarily point a consumer branch at the commit (`uvx --from git+https://github.com/outernet-foundation/release-devkit@<ref>`) and revert; the standing pin never rides an unreleased commit.

An inline `run:` step executes in the caller's job, so `job_workflow_ref` resolves to the **caller's** workflow file: the OIDC trusted-publishing identity is the caller's own, which is the property PyPI hard-requires (warehouse#11096 blocks reusable-workflow publishers) and npm binds (the caller's top-level workflow filename). Inline steps and composite actions are OIDC-safe; reusable workflows are not — the publish jobs must never be converted to one.

## Self-publication

release-devkit is the one repo that consumes itself from local source rather than from PyPI: it *is* release-devkit, so its own `ci-cd.yml` runs `uv run publish-stable` / `publish-dev` / `ensure-release-pr`, plus `publish-stable --dry-run` as the trailing step of its `check` job — no uvx, no `RELEASE_DEVKIT_VERSION` self-reference. Everything else in its `ci-cd.yml` follows the shared shape: `check` runs `preflight-python` from the python-devkit dev dependency (release-devkit is not self-preflighting), and the publish jobs carry the same `environment: release`, permissions, and concurrency as every other consumer. Its dependencies must all exist on PyPI before it publishes. The committed `pyproject.toml` version is permanently the `0.0.0.dev0` sentinel; the `release-devkit-v*` tags are the version ledger. All three devkits are preproduction: breaking changes ride the current `0.1` patch line; a `major_minor` bump is reserved for the eventual 1.0.0 stabilization release.

## Commands

Each is a `uv run <name> --config <path>` from the consuming repo's root in release-devkit's own self-publish CI; consumers invoke each as `uvx --from release-devkit==<version> <name>` in their publish jobs. Config defaults to `release-devkit.yaml` where optional.

| Command | Role |
|---|---|
| `app-build-version` | Print the version a CI build of an app should stamp: `{next_version}+{run}` — `next_version` derived from the app's declared `major_minor` and the `{name}-v*` tag ledger (prerelease-suffixed tags excluded; no in-line tag → `{major_minor}.0`), the same `next_version` `publish-stable` uses to tag the release so the build-time stamp matches the eventual release tag. Run number from `--run-number` or `GITHUB_RUN_NUMBER`. The build-time half of the versioning boundary: this tool owns version derivation, build tools own stamping, and the consumer's workflow bridges the two — the emitted string is opaque to the build door that receives it. |
| `publish-stable` | Compute the publish plan from the tag ledger + path-diff, publish every changed package to its registries, bump and tag app versions, push per-package tags, then cut the GitHub Release (`create-release` runs internally whenever something published — there is no `published` output and no separate gated step). `--dry-run` prints the plan and runs every plan-time validation without publishing. `--fetch-ci-artifacts` fetches CI build artifacts (`fetch-ci-artifacts` runs internally) and staples them onto that release. |
| `publish-dev` | Dev-channel mode: publish immutable `-dev.<run-id>` prereleases of every path-diff-changed package to its registries. `--run-id` defaults to `GITHUB_RUN_ID`; never creates git tags, never touches app versions. |
| `create-release` | Assemble release notes (package versions with registry links, app versions), package CI artifacts, and cut the CalVer-named (`YYYY.MM.N`, counting releases within the month) GitHub Release. `publish-stable` calls it internally on every real publish; as a standalone verb it exists for manual re-creates. |
| `ensure-release-pr` | Maintain the standing `dev` → `main` "Next release" gate PR. |
| `fetch-ci-artifacts` | Locate the successful CI run for the release SHA (via the merge commit's second parent) and download its artifacts, pruning non-release ones per the config's skip rules. Invoked inside `publish-stable` via `--fetch-ci-artifacts`; as a standalone verb for manual fetches. |

## Consumption shape

Every consumer runs one workflow file, `ci-cd.yml`, combining CI and release. Triggers: `workflow_dispatch`, `push: [main, dev]`, `pull_request: [dev]` — never `workflow_run` (it was only ever the bridge between two files; one file means `needs` is the green gate) and never `pull_request: [main]`: the standing release PR's head is the dev tip that just ran identical CI via the push event, so letting it fire doubles CI (including the QEMU matrices) on every dev push. Consequence: the release PR reports zero checks; `main`'s branch protection must require no status checks. Exactly one workflow-level concurrency block and zero per-job blocks:

```yaml
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}
```

Superseded runs on the same branch cancel whole; `main` runs queue instead — and `publish-stable`, the one job that must never die mid-release, is only reachable from `main`, where cancel is off (the queue is the publish mutex). A cancelled dev publish is safe by construction: `-dev.<run-id>` prereleases are immutable, create no tags, and the successor run re-points the npm `dev` dist-tag; killing a stale run also kills its `ensure-release-pr` bot tick, which removes the duplicate-PR race. CI jobs (`check`, `mirror`, builds) are gated `if: github.ref != 'refs/heads/main'`; `publish-stable` runs `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`; `publish-dev` and `ensure-release-pr` run on `dev` push.

The needs-chain law: `check` is the root; `publish-dev` needs the DAG sinks of the repo's build jobs; `needs` is transitive, so ancestors are never re-listed. The one sanctioned deviation: a `mirror` job may run as the parallel root ahead of `check` — mirror is a near-always no-op (existence probes; only changed entries copy), so serializing it behind `check` buys nothing, and when `check` itself consumes mirror-prefixed images (placeframe's postgres-wrapper preflight build) the inversion is forced anyway. Chaining expensive builds behind `check` matters because `check`'s trailing dry-run fails a broken `release-devkit.yaml` at minute 3 instead of after a 40-minute build that could never ship.

Consumers inline the verbs directly in their `ci-cd.yml` jobs — no composites in this repo, no consumer-local bootstrap action, no vendored checkout. Each verb-owning job owns its checkout and runs `uvx --from release-devkit==${{ env.RELEASE_DEVKIT_VERSION }} <name>` steps (workflow-level `env:`). Any job invoking a ledger-reading verb (`publish-stable` incl. `--dry-run`, `publish-dev`, `ensure-release-pr`, `app-build-version`) checks out with `fetch-depth: 0` + `fetch-tags: true` and no separate fetch step (`fetch-tags` is broken with shallow clones), `persist-credentials: false` everywhere except `publish-stable`, whose credentials must persist for the tag push:

- `check` (every repo) — ledger checkout + setup-uv + the python battery, with `publish-stable --dry-run` as the trailing step (the publish-plan gate). App repos fold `app-build-version --app <name>` into the same job, exporting the version as a job output for the build workflow — no separate `resolve-version` job.
- `ensure-release-pr` — ledger checkout + setup-uv + `ensure-release-pr`, **no `needs`**: it consumes no CI output, and a standing PR tracking a red dev branch is the accurate state. Job env `GH_TOKEN`.
- `publish-stable` — checkout (`ref: main`, ledger shape, credentials persisting for the tag push) + setup-uv + `publish-stable [--with-apps] [--fetch-ci-artifacts]`, step env `NPM_CONFIG_LOGLEVEL: verbose` (npm OIDC diagnostics; no-op elsewhere). Job env `GH_TOKEN`, `NUGET_API_KEY`; permissions `contents: write` + `id-token: write`, plus `actions: read` when `--fetch-ci-artifacts`. The GitHub Release is cut inside the command — no separate `create-release` step.
- `publish-dev` — a normal job in the dev-push run, not a `workflow_run` follow-up: default checkout (the pushed dev SHA, ledger shape) + setup-uv + `publish-dev` with no `--run-id` (the default `GITHUB_RUN_ID` is the correct number), step env `NPM_CONFIG_LOGLEVEL: verbose`. No tags, no releases.

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
- `ci_workflow` is required: it is the `fetch-ci-artifacts` lookup key (`gh api …/workflows/{name}/runs?head_sha=…`) that disambiguates which workflow's artifacts to staple onto a release — several workflows run on the release SHA, including Release itself, so a `"ci.yml"` default would be silently wrong for repos whose CI file is named differently.
- The mapping fields (`packages`, `apps`) may be omitted when empty — an apps-only repo declares no `packages` key at all. Both key packages and apps by name, which doubles as the git-tag prefix (`{name}-v{semver}`); apps carry no separate `display_name` or `tag_prefix`.
- `requires` is a required PEP 440 specifier (e.g. `requires: ">=0.1.18"`); `load_config` self-checks the installed release-devkit version against it and refuses loudly outside the range (the terraform pattern). Omission is a validation error, not a silent skip — "no constraint" is explicit `requires: ">=0.0"`. The `0.0.0.dev0` dev sentinel bypasses the *check* (running the tool's own checkout is never blocked), not the field's presence; this repo's own `release-devkit.yaml` carries `requires: ">=0.1"`.

## See also

- `README.md` — human-facing usage and consumption wiring.
- [`bashrun`](https://github.com/outernet-foundation/bashrun) — the subprocess wrapper every shell-out goes through.
