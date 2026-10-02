# release-devkit

Publication machinery for multi-registry package releases: a per-package git-tag ledger, path-diff change detection, ephemeral version patching, manifest-inferred dependency edges, registry adapters (nuget, npm/UPM, PyPI), and release orchestration — all driven by a declarative, consumer-owned config.

Every consuming repo keeps only a root `release-devkit.yaml` (package identities, paths, version lines, registry mappings, builds shelves), a one-step wrapper action pinning this toolkit at a full commit SHA, and workflow jobs that invoke its composite actions. See [`AGENTS.md`](./AGENTS.md) for the invariants (CI-commit-free releases, tag-ledger versioning, the `0.0.0+local` dependency sentinel and reference regimes, ephemeral manifest version patching) and the command catalog.

## Requirements

- Python 3.13+ and [uv](https://docs.astral.sh/uv/) (uv provisions everything; the composite actions run `uv run --project` against the checkout's lock)
- At runtime: `git`, `gh`, `dotnet` (nuget publish), `node`/`npm` (npm publish), `uv` (PyPI publish via trusted publishing), `oras` (builds-shelf pulls — auto-provisioned on Linux/Windows)

## Consuming from another repo

Install nothing and pin a version — release-devkit is **published nowhere**: it is consumed exclusively as a git checkout at a full commit SHA (never a branch or tag — a movable ref reintroduces version float), through the composite actions in this repo. The pin lives in one place per consuming repo — a wrapper action, `.github/actions/checkout-release-devkit/action.yml`, whose single step checks this repo out directly. (An earlier design routed the wrapper through a devkit-side "self-versioning" checkout action using `github.action_repository`/`action_ref`; those context values do not rebind through nested composite actions, so the wrapper checked out the wrong repository. The direct checkout is the fix — one step, one SHA mention.) Every verb-owning job runs that wrapper beside the consumer's own checkout and then invokes the verb's action locally, so the action glue and the tool are the same checkout at the same SHA:

```yaml
# .github/actions/checkout-release-devkit/action.yml — the whole wrapper
name: checkout-release-devkit
description: Check out release-devkit at the pinned commit
runs:
  using: composite
  steps:
    - uses: actions/checkout@v5
      with:
        repository: outernet-foundation/release-devkit
        ref: <full 40-char commit sha>
        path: .release-devkit
        persist-credentials: false
```

```yaml
# a delivery job in .github/workflows/publish.yml
jobs:
  publish-stable:
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment: release
    permissions:
      contents: write
      id-token: write
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
          fetch-tags: true

      - uses: ./.github/actions/checkout-release-devkit

      - uses: ./.release-devkit/.github/actions/publish-stable
```

The job owns both checkouts: the consumer repo first (ledger shape — `fetch-depth: 0` + `fetch-tags: true`; on `publish-stable` the default persisting credentials are what the tag push needs), then the wrapper. The action runs the verb as `uv run --project "$GITHUB_WORKSPACE/.release-devkit" --locked --no-dev <verb>` and self-serves the env it needs (`GH_TOKEN`, `CI_REGISTRY_*`). Available actions: `publish-stable` (input `dry-run`), `publish-prerelease`, `ensure-release-pr`, `get-app-version` (input `app`, output `version`), `lint-ci` — none of them checks anything out; each assumes the caller already holds the consumer checkout.

The steps run inside the caller's job, so the OIDC trusted-publishing identity stays the caller's own workflow — PyPI hard-blocks reusable-workflow publishers, which is why the verbs ride composite actions inlined into the caller's workflow rather than a reusable workflow.

Build tooling consumes the same ledger at build time: `get-app-version --app <name>` prints the
version a CI build of an app should stamp — `{next_version}+{run}`, the run number coming from
`--run-number` or the ambient CI run number. The emitted string is opaque to the build door that
receives it: version derivation lives here, stamping belongs to the build tool, and the consumer's
workflow bridges the two.

Then author root `release-devkit.yaml`:

```yaml
ci_workflow: publish.yml
packages:
  my-api-client:
    path: generated/csharp/api-client/src/MyApiClient
    major_minor: "0.1"
    registries:
      nuget: MyApiClient
      npm: org.example.myproject.apiclient
  my-core:
    path: packages/unity/Core
    major_minor: "1.0"
    registries:
      npm: org.example.myproject
  my-arfoundation:
    path: packages/unity/ARFoundation
    major_minor: "1.0"
    registries:
      npm: org.example.myproject.arfoundation
apps:
  MyTool:
    path: apps/MyTool
    major_minor: "1.0"
    builds:
      registry: ghcr.io/my-org/my-repo/builds
      artifacts:
        - project: MyTool
          platform: AndroidMobile
          file: My_Tool.apk
          name: MyTool-AndroidMobile.apk
```

Dependencies between packages in one config are **not** authored here: they are inferred from the manifests (package.json dependencies, `[project].dependencies`, csproj `PackageReference`), and same-unit dependencies are authored in those manifests as the sentinel `0.0.0+local` — the concrete sibling version is injected at publish time from the event's ledger. `AGENTS.md` carries the full dependency-edge law and reference regimes.

`ci_workflow` names the workflow whose build outputs a release staples (the matched-run lookup key — it disambiguates among the several workflows that run on the release SHA, so it stays explicit; post-split it is `publish.yml`). The `builds` section declares the shelf each app's release assets pull from at the matched run: `project`/`platform` compose the shelf address exactly as the push side did (`file` picks the layer when a build pushes several; `name` renames the asset).

and invoke from a checkout (local runs):

```bash
uv run publish-stable --config release-devkit.yaml
uv run publish-prerelease --config release-devkit.yaml
uv run create-release --config release-devkit.yaml
```

The mapping fields (`packages`, `apps`) may be omitted when empty — an apps-only repo (no registry packages) declares no `packages` key at all.

`publish-prerelease` is the dev-channel job: it publishes immutable `-dev.<run-id>` prereleases (`X.Y.Z.dev<run-id>` on PyPI) of every changed package on a green push — no git tags, npm `latest` untouched — and prints the exact versions to pin.

Environment (via pydantic-settings): `GITHUB_WORKSPACE`, `GITHUB_REPOSITORY`, `GITHUB_SHA`, `GITHUB_STEP_SUMMARY`, `GITHUB_OUTPUT`, `GITHUB_RUN_ID`, `NUGET_API_KEY`; builds-shelf pulls authenticate through ci-devkit's neutral chain (`CI_REGISTRY_USERNAME`/`CI_REGISTRY_TOKEN`, or an ambient docker credential config).

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
uv run pytest
```
