# release-devkit

## What this is

The publication machinery for outernet-foundation repos: the publish pipeline, the per-package tag ledger and path-diff change detection, ephemeral version patching, manifest-inferred dependency edges, and release orchestration. A standalone repo (sibling of `unity-devkit` / `docker-devkit` / `bashrun`), published to PyPI and consumed **uvx-isolated** — it is a project dependency of nothing. The reason is structural: every tool repo it publishes sits inside its own dependency graph (bashrun and ci-devkit are release-devkit's runtime deps), so a project-level release-devkit edge in those repos is a resolver cycle plus a root-version conflict against the committed version sentinel. Consumers outside that graph (placeframe) use uvx for the same shape, keeping one consumption model. Publish jobs in consumer repos inline the same uvx invocation as plain steps in the caller's workflow, so the OIDC trusted-publishing identity stays the caller's own workflow file — PyPI hard-blocks reusable-workflow publishers (warehouse#11096) and npm binds the caller's top-level workflow filename, which is why publication inlines the call in the caller's workflow, never a reusable workflow. The version pin lives in each consumer's workflow file.

The consumer owns everything declarative: package and app identities, paths, and registry mappings live in a consumer-authored `release-devkit.json` at the repo root; every command here reads that file. Per-repo copies of this machinery are refused, as are per-ecosystem splits — the seam is internal: one `Registry` adapter per registry over the shared ledger/diff/versioning core.

The package is `release-devkit` (src-layout under `src/release_devkit/`; import `release_devkit`). Runtime dependencies: `bashrun` (all shell-outs), `ci-devkit` (`ci_step`, runner setup), `pydantic`/`pydantic-settings` (config + CI env), `typer` (CLIs) — all from PyPI, zero domain dependencies.

## Self-publication

release-devkit publishes itself from its own checkout: `release.yml` — triggered by a successful CI run on a `main` push — runs `uv run publish-stable --config release-devkit.json`; the repo *is* release-devkit, so no uvx bootstrap and no self-reference. Its dependencies must all exist on PyPI before it publishes. The committed `pyproject.toml` version is permanently the `0.0.0.dev0` sentinel; the `release-devkit-v*` tags are the version ledger. All three devkits are preproduction: breaking changes ride the current `0.1` patch line; a `major_minor` bump is reserved for the eventual 1.0.0 stabilization release.

## Commands

All are `uv run <name> --config <path>` from the consuming repo's root (config defaults to `release-devkit.json` where optional).

| Command | Role |
|---|---|
| `app-build-version` | Print the version a CI build of an app should stamp: the app's latest stable `{name}-v*` ledger tag (prerelease-suffixed tags excluded, fallback `0.0.0`) plus the build number — `{version}+{run}` when `GITHUB_REF_NAME` is `main`, `{version}-dev+{run}` otherwise; run number from `--run-number` or `GITHUB_RUN_NUMBER`. The build-time half of the versioning boundary: this tool owns version derivation, build tools own stamping, and the consumer's workflow bridges the two — the emitted string is opaque to the build door that receives it. |
| `publish-stable` | Compute the publish plan from the tag ledger + path-diff, publish every changed package to its registries, bump and tag app versions, push per-package tags. `--dry-run` prints the plan and runs every plan-time validation without publishing. |
| `publish-dev` | Dev-channel mode: publish immutable `-dev.<run-id>` prereleases of every path-diff-changed package to its registries. `--run-id` defaults to `GITHUB_RUN_ID`; never creates git tags, never touches app versions. |
| `create-release` | Assemble release notes (package versions with registry links, app versions), package CI artifacts, and cut the CalVer-named (`YYYY.MM.N`, counting releases within the month) GitHub Release. Runs only when something published — consumer workflows gate the step on `publish-stable`'s `published` output. |
| `ensure-release-pr` | Maintain the standing `dev` → `main` "Next release" gate PR. |
| `fetch-ci-artifacts` | Locate the successful CI run for the release SHA (via the merge commit's second parent) and download its artifacts, pruning non-release ones per the config's skip rules. |

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

`config.PublishConfig` (pydantic, loaded by `load_config`) validates the consumer's root `release-devkit.json`. The config-file law org-wide: config names its owning devkit and lives beside the unit whose facts it carries — project-dep devkits configure via `[tool.<devkit>.*]` pyproject tables; uvx-isolated devkits via one root `<devkit>.json` per repo (this file is that law's home; siblings reference it, they don't duplicate it).

- The registry-mapping key is `registries`. Hard flip, no accept-both: unknown keys are rejected (`extra="forbid"`), so an unmigrated config fails loudly at load instead of silently publishing with zero registries.
- `ci_workflow` is required: it is the `fetch-ci-artifacts` lookup key (`gh api …/workflows/{name}/runs?head_sha=…`) that disambiguates which workflow's artifacts to staple onto a release — several workflows run on the release SHA, including Release itself, so a `"ci.yml"` default would be silently wrong for repos whose CI file is named differently.
- The mapping fields (`packages`, `apps`) may be omitted when empty — an apps-only repo declares no `packages` key at all. Both key packages and apps by name, which doubles as the git-tag prefix (`{name}-v{semver}`); apps carry no separate `display_name` or `tag_prefix`.

## See also

- `README.md` — human-facing usage and consumption wiring.
- [`bashrun`](https://github.com/outernet-foundation/bashrun) — the subprocess wrapper every shell-out goes through.
