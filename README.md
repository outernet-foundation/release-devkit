# release-devkit

Publication machinery for multi-registry package releases: a per-package git-tag ledger, path-diff change detection, ephemeral version patching, manifest-inferred dependency edges, registry adapters (nuget, npm/UPM, PyPI), and release orchestration — all driven by a declarative, consumer-owned config.

Every consuming repo keeps only a root `release-devkit.yaml` (package identities, paths, version lines, registry mappings, builds shelves), a two-step setup action pinning this toolkit at a full commit SHA, and workflow jobs whose run steps invoke its verbs. See [`AGENTS.md`](./AGENTS.md) for the invariants (CI-commit-free releases, tag-ledger versioning, the `0.0.0+local` dependency sentinel and reference regimes, ephemeral manifest version patching) and the command catalog.

## Requirements

- Python 3.13+ and [uv](https://docs.astral.sh/uv/) (uv provisions everything; verb run steps execute `uv run --project` against the installed checkout's lock)
- At runtime: `git`, `gh`, `dotnet` (nuget publish), `node`/`npm` (npm publish), `uv` (PyPI publish via trusted publishing), `oras` (builds-shelf pulls — auto-provisioned on Linux/Windows)

## Consuming from another repo

Install nothing and pin a version — release-devkit is **published nowhere**: it is consumed exclusively as a git clone at a full commit SHA (never a branch or tag — a movable ref reintroduces version float), installed onto the runner machine by a per-consumer setup action. The pin lives in one place per consuming repo — `.github/actions/setup-release-devkit/action.yml` — whose first step installs uv and whose second is a tokenless `git clone` of the public repo into `$RUNNER_TEMP/release-devkit` with `git checkout` of the pinned SHA. The install location keeps the devkit out of the consumer's workspace (the consumer's own linters never scan devkit code) and matches where the runner already puts its tooling. Every verb-owning job runs that wrapper after the consumer's own checkout and then invokes verbs as plain run steps:

```yaml
# .github/actions/setup-release-devkit/action.yml — the whole wrapper
name: setup-release-devkit
description: Install release-devkit at the pinned commit into RUNNER_TEMP
runs:
  using: composite
  steps:
    - uses: astral-sh/setup-uv@v7
      with:
        enable-cache: true
    - shell: bash
      run: >
        git clone https://github.com/outernet-foundation/release-devkit.git "$RUNNER_TEMP/release-devkit"
        && git -C "$RUNNER_TEMP/release-devkit" checkout <full 40-char commit sha>
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

      - uses: ./.github/actions/setup-release-devkit

      - name: publish-stable
        run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev publish-stable
        env:
          GH_TOKEN: ${{ github.token }}
          CI_REGISTRY_USERNAME: ${{ github.actor }}
          CI_REGISTRY_TOKEN: ${{ github.token }}
```

The job owns its own checkout (ledger shape — `fetch-depth: 0` + `fetch-tags: true`; on `publish-stable` the default persisting credentials are what the tag push needs), then the wrapper installs the tool. Each verb is one run step — `uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev <verb>` from the consumer root, with the env that verb needs spelled in the step (`GH_TOKEN`, `CI_REGISTRY_USERNAME`/`CI_REGISTRY_TOKEN`). Verbs: `publish-stable` (flag `--dry-run`), `publish-prerelease`, `ensure-release-pr` (env `GH_TOKEN`), `get-app-version` (flag `--app <name>`; export via the step output you wrap around it), `lint-ci`. `lint-ci` validates the wrapper shape, the invocation spellings, and the checkout/ordering contract mechanically.

The run steps execute inside the caller's job, so the OIDC trusted-publishing identity stays the caller's own workflow — PyPI hard-blocks reusable-workflow publishers, which is why the verbs are plain run steps in the caller's workflow rather than a reusable workflow.

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
