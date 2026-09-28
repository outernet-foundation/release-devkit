# release-devkit

Publication machinery for multi-registry package releases: a per-package git-tag ledger, path-diff change detection, ephemeral version patching, manifest-inferred dependency edges, registry adapters (nuget, npm/UPM, PyPI), and release orchestration — all driven by a declarative, consumer-owned config.

Every consuming repo keeps only a root `release-devkit.yaml` (package identities, paths, version lines, registry mappings) and workflow steps that are thin `uvx` invocations. See [`AGENTS.md`](./AGENTS.md) for the invariants (CI-commit-free releases, tag-ledger versioning, the `0.0.0+local` dependency sentinel and reference regimes, ephemeral manifest version patching) and the command catalog.

## Requirements

- Python 3.13+ and [uv](https://docs.astral.sh/uv/)
- At runtime: `git`, `gh`, `dotnet` (nuget publish), `node`/`npm` (npm publish), `uv` (PyPI publish via trusted publishing)

## Consuming from another repo

Install nothing — release-devkit is consumed **uvx-isolated** (it is a project dependency of nothing: the tool repos it publishes sit inside its own dependency graph, where a project-level release-devkit edge is a resolver cycle). Publish jobs inline the invocation as plain steps in the caller's workflow:

```yaml
jobs:
  publish:
    permissions:
      contents: write
      id-token: write
    steps:
      - uses: actions/checkout@v5

      # Workaround: fetch-tags is broken with shallow clones
      - run: git fetch --tags origin

      - uses: astral-sh/setup-uv@v7

      - name: Publish
        run: uvx --from release-devkit==0.1.14 publish-stable --config release-devkit.yaml
```

The uvx invocation runs inside the caller's job, so the OIDC trusted-publishing identity stays the caller's own workflow — PyPI hard-blocks reusable-workflow publishers, which is why the call inlines in the caller's workflow rather than riding a reusable workflow. Direct uvx is the same shape anywhere else:

```bash
uvx --from release-devkit==0.1.14 publish-stable --config release-devkit.yaml
```

Build tooling consumes the same ledger at build time: `app-build-version --app <name>` prints the
version a CI build of an app should stamp — `{version}-dev+{run}` off-main, `{version}+{run}` when
`GITHUB_REF_NAME` is `main`; the run number comes from `--run-number` or `GITHUB_RUN_NUMBER`. The
emitted string is opaque to the build door that receives it: version derivation lives here,
stamping belongs to the build tool, and the consumer's workflow bridges the two.

Then author root `release-devkit.yaml`:

```yaml
ci_workflow: my-ci.yml
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
```

Dependencies between packages in one config are **not** authored here: they are inferred from the manifests (package.json dependencies, `[project].dependencies`, csproj `PackageReference`), and same-unit dependencies are authored in those manifests as the sentinel `0.0.0+local` — the concrete sibling version is injected at publish time from the event's ledger. `AGENTS.md` carries the full dependency-edge law and reference regimes.

`ci_workflow` names the CI workflow whose artifacts a release staples (the `fetch-ci-artifacts` lookup key — it disambiguates among the several workflows that run on the release SHA, so it stays explicit).

and invoke from CI:

```bash
uvx --from release-devkit==0.1.14 publish-stable --config release-devkit.yaml
uvx --from release-devkit==0.1.14 publish-dev --config release-devkit.yaml --run-id ${{ github.event.workflow_run.id }}
uvx --from release-devkit==0.1.14 create-release --config release-devkit.yaml
```

The mapping fields (`packages`, `apps`) may be omitted when empty — an apps-only repo (no registry packages) declares no `packages` key at all.

`publish-dev` is the dev-channel job: it publishes immutable `-dev.<run-id>` prereleases (`X.Y.Z.dev<run-id>` on PyPI) of every changed package on a green push — no git tags, npm `latest` untouched — and prints the exact versions to pin.

Environment (via pydantic-settings): `GITHUB_WORKSPACE`, `GITHUB_REPOSITORY`, `GITHUB_SHA`, `GITHUB_STEP_SUMMARY`, `GITHUB_OUTPUT`, `GITHUB_RUN_ID`, `NUGET_API_KEY`.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
uv run pytest
```
