# Reusable-Workflow Migration — collapse the trim-lint into devkit-owned workflows

Status: plan drafted 2026-10-09 from the architecture session. The "Resolve first" section is
where the next session opens: those answers are inputs to every phase below, not editorial
polish. Once resolved, decisions are binding for execution sessions. Cadence: one session per
PR where practical, each landing on `dev` via the repo's own merge-gate; commit discipline per
AGENTS-SHARED (prose and code in separate commits, no trailers). This plan supersedes the
remaining sweep scope of `release-devkit-finish.md` for `integrate.yml` / `merge-gate.yml`
(`ci-refresh-seed.md` folds into Phase 6 below); `release.yml` conformance items from
`zizmor-audit.md` still ride the cutover.

## Resolve first (next session starts here)

Each question carries the session's recommended default; confirm or override, then execute.

1. **Execution scope of the next session.** Recommendation: Phase 1 (release-devkit's
   reusables + lint rewrite + self-host cutover) plus Phase 2 (pilot consumer `bashrun`) only;
   remaining phases get their own sessions. The full plan spans four repos and 19 consumers —
   not one session's work.
2. **`verify.yml` bundles lint ∥ validate.** Recommendation: yes — one reusable containing
   `lint-workflows` and `validate-release-plan` as internal parallel jobs with the fail-fast
   `needs` contract internal, exporting `version`/`version-code`, optional `app-name` input.
   Alternative (two separate reusables, caller-side `needs`) re-opens the needs-contract drift
   the bundle exists to kill.
3. **Same-SHA law covers the wrapper.** Recommendation: yes — the lint reads
   `.github/actions/setup-release-devkit/action.yml`'s `RELEASE_DEVKIT_COMMIT` and requires it
   equal to every release-devkit `uses:` SHA in the repo. One law, one SHA per devkit per
   consumer, both spellings.
4. **`free_disk_space` policy** in docker-devkit's absorbed CI shim. Recommendation: a
   `docker-devkit.yaml` toggle (the devkit's existing per-consumer-variance pattern), default
   on for CI mode; placeframe's current argument set is the default.
5. **Preflight reusables** (a python-devkit `preflight-python.yml` for simple repos).
   Recommendation: out of scope; record as a follow-up phase only.
6. **Doc name.** Recommendation: keep `plan-reusable-workflow-migration.md`.
7. **release.yml delivery via a devkit-owned composite action.** Recommendation: yes — trusted
   publishing binds (repo, workflow filename) and composite steps execute inside the caller's
   job, so `job_workflow_ref` keeps naming the consumer's `release.yml` (the identity reusable
   workflows break — warehouse#11096 does not reach composites). A `.github/actions/release`
   composite (inputs `channel`, `nuget`) absorbs the checkout/tag-fetch law, setup-uv, nuget
   login, and the verb invocation; it self-installs the devkit (verify `github.action_ref`
   resolves to the called SHA inside a cross-repo composite — the composite analogue of
   `job.workflow_sha`; fallback: `github.action_path` off a root `action.yml`, where the
   runner's archive download is the install). The per-consumer `setup-release-devkit` wrapper
   and `RELEASE_DEVKIT_COMMIT` die fleet-wide, not just for reusable jobs. Verify once, in the
   bashrun pilot, that PyPI trusted publishing accepts a publish through composite-wrapped
   steps; fallback if it rejects: release.yml keeps inline verbs and only the wrapper dies.
   Confirming this supersedes Phase 6's "inline verbs and wrapper install are untouched"
   clause and the wrapper-validation rows of the disposition table.
8. **How far to gut `lint-workflows`.** Recommendation: actionlint + zizmor + the SHA law, plus
   a small irreducible residue: (a) the inline-delivery law retargeted — delivery jobs must
   call the composite action, never a reusable workflow (enforceable only on consumer files);
   (b) release.yml's concurrency no-cancel (the delivery mutex); (c) merge-gate's labeled-only
   wake and per-PR serializing group (arguably droppable — zizmor already bans `workflow_run`
   and the verb re-derives every precondition on any wake; the surviving failure mode is a
   racing double-merge). Everything else — verb grammar and spec tables, ref laws, tag-fetch
   laws, verb-installation, env-reference resolution, wrapper validation, one-saver-cache, the
   nuget-key env law (whose `declares_nuget()` is the lint's only `release-devkit.yaml` read —
   content validation already lives in pydantic config load and `validate-release-plan`), and
   the `environment:` ban — dies into the single-copy devkit artifacts or is already
   actionlint/zizmor territory.

## Thesis

The trim-lint enforces, across 19 hand-written consumer files, what is fundamentally a
copy-paste relationship: each consumer's `integrate.yml` / `merge-gate.yml` restates identical
structure (checkout ref laws, fetch tags, wrapper install, verb invocations, unity matrix
getter + fanout, docker matrix + legs) that belongs to the devkits, and the lint exists to
police the copies. GitHub reusable workflows can hold that structure once, in the owning
devkit repo, where it cannot drift because there is exactly one copy. The lint then shrinks to
what genuinely cannot be centralized: `on:` triggers, concurrency shape, the SHA pin law, and
the whole `release.yml` contract (which stays hand-written because trusted publishing requires
inline `run:` jobs — PyPI still hard-blocks reusable-workflow trusted publishers,
pypi/warehouse#11096; npm and nuget.org bind the workflow filename the same way).

Decision (operator, 2026-10-09): **pinning is lint-enforced multi-spelling.** Literal
`@<full-sha>` at every call site; `lint-workflows` enforces full-SHA shape and one SHA per
devkit repo per consumer. Routers/dispatcher muxes were designed and rejected (flat
`workflow_call` input surface forces union-forwarding that grows with the devkit vocabulary);
generated pins from a single authored file were designed and rejected (operator's call). The
failure mode of multi-spelling is a loud lint failure, not silent drift.

## Verified platform mechanics (do not re-derive; researched 2026-10-09)

- **Composition is job-level.** A caller workflow mixes local jobs and `uses:` calls freely;
  `needs` wires across both. A calling job accepts only `needs`, `if`, `permissions`, `with`,
  `secrets`, `strategy`, `concurrency`, `name` — never `steps`, `runs-on`, `container`, `env`.
  Inside the called workflow everything is an ordinary workflow: multi-job graphs, internal
  `needs`, a getter job emitting `$GITHUB_OUTPUT` consumed by a fanout via
  `strategy.matrix: ${{ fromJson(needs.matrix.outputs.matrix) }}`, `container:` from matrix,
  `fail-fast`. Matrix at the call site also works but is not the chosen shape.
- **Self-checkout is first-class.** `job.workflow_repository` + `job.workflow_sha` give a
  called workflow its own resolved repo and SHA — `actions/checkout` with those checks the
  devkit out at exactly the pin the caller spelled. This is release-devkit's install mechanism
  inside its reusables (it is never a consumer dependency); the `setup-release-devkit` clone
  dance dies for every job that goes reusable.
- **`uses:` is resolved statically by GitHub, server-side, before any runner exists.** No
  expressions, no env, no filesystem. Cross-repo refs must be `owner/repo/.github/workflows/
  file.yml@ref`; `./` and `$/` refs resolve same-repo at the caller's commit. Consequence: a
  consumer's SHA can only be spelled in the consumer's own files; a composite action can never
  front a workflow call; release-devkit's own `integrate.yml` calls its own reusables via
  `./` refs with **no SHA and no self-pin bump** — the static self-pin machinery dies.
- **Same-org self-hosted runners work in called workflows** (callee uses the caller's runner
  pool); the org `unity` runners qualify. `github` context in the callee is the caller's
  event (PR-gate `if`s, `GITHUB_REF` parsing, `github.repository` registry derivation all
  keep working). Caller's `vars` are visible; secrets must be passed per call and forwarded
  explicitly at every nesting hop (docs: secrets reach only the directly called workflow).
  `GITHUB_TOKEN` permissions propagate maintain-or-reduce from the call site — callers grant,
  callees cannot elevate.
- **Outputs chain** through `on.workflow_call.outputs` at each level; matrix/`needs` consumers
  in the caller read `needs.<calling-job>.outputs.*` normally.
- **Footguns.** `fromJson` on an empty string fails the workflow at render time (our matrix
  verbs always emit valid JSON; this is the signature of a quietly failing getter). Nested
  limit is 10 levels (this plan uses at most 2). actionlint 1.7.12 may not know the `job.*`
  context — verify against its release notes and bump the pin in `lint_workflows.py` if
  needed (Phase 1). Matrix-derived values interpolated into `run:` lines ride step `env` with
  the run line referencing the variable — zizmor's template-injection remediation, the
  standing law; the new devkit-owned workflow files must conform (they are audited by each
  consumer's `verify.yml` lint pass and by each devkit's own self-lint).

## Deliverables

### Phase 1 — release-devkit

New reusable workflows in this repo's `.github/workflows/`, each self-checking-out via
`job.workflow_repository`/`job.workflow_sha`, third-party action SHAs pinned once here
(wrapper-per-action law applies inside this repo):

- `verify.yml` — internal parallel jobs `lint-workflows` (the verb: actionlint + zizmor +
  signature validation over the consumer's remaining files) and `validate-release-plan`
  (checkout PR-head ref law + `fetch-depth: 0` + `fetch-tags: true` internal); when the
  optional `app-name` input is set, `get-app-version --app <name>` runs in the validate job
  and the workflow exports `version`/`version-code`.
- `update-pr-draft-release.yml` — `release --channel pr`; `if: github.event.pull_request`
  internal; `packages: read` granted at call site; needs the consumer's terminal build legs
  at the call site (it staples the shelf at the PR head).
- `merge-gate.yml` — full-clone checkout of the PR head, internal mint of the merge-bot App
  token (`vars.MERGE_BOT_APP_ID` reads the caller's var; the key arrives as a named secret,
  `merge-bot-private-key`), `merge-gate --head-sha` invocation.

Lint rewrite (see disposition table): add the SHA law and inline-delivery enforcement; delete
the integrate/merge-gate grammar. Own `integrate.yml`/`merge-gate.yml` cut over to `./` calls
(no self-pin). AGENTS.md rewritten spec-first in the same PR set (separate prose commit).

### Phase 3 — unity-devkit

- `build.yml` and `compile-check.yml`, each containing the matrix getter
  (`build-unity-matrix` / `compile-check-unity-matrix`) **and** the fanout
  (`ci-build-unity` / `compile-check-unity`) internally: `runs-on: [self-hosted, unity]`,
  `container: ${{ matrix.editor-image }}`, wipe-workspace, checkout + setup-uv restore,
  license `--license` threading, unity secrets (`unity-email`/`unity-password`/
  `unity-serial`, named), registry auth ambient. Inputs: `version` (string, from the caller's
  `needs.verify.outputs.version`), optional `project` scoping passthrough.
- Structure-only centralization: verb code still resolves from the consumer's `uv.lock`
  (unity-devkit stays a PyPI dep). The `@sha` pins workflow *structure*; the lock pins *code*
  — coherent bumps do both together. Its AGENTS.md "Consumer CI template" section is replaced
  by the reusable reference.

### Phase 4 — docker-devkit

Code moves (release-train: consumers take them via floor-bump/relock, not workflow edits):

1. Absorb the CI shim into the `build --mode ci` path (or a `ci-build` entry point mirroring
   unity-devkit's shape): `configure_git`, `free_disk_space` (toggle per Resolve-first #4),
   `docker buildx create`, ghcr login from ambient `github.actor`/`github.token`. Deletes
   placeframe's 53-line `ci/build_docker.py` wrapper; capture-tool's workflow-level
   QEMU/buildx/login steps die the same way (QEMU arm64 stays one setup step inside the
   reusable, or binfmt-from-manifest if trivial).
2. Teach `docker-build-matrix` the cross-compile cohort: emit legs for
   `x-cross-compile-targets` and platform-pinned services (entries carry a `platform` fact
   from the manifest's `platforms:` keys). capture-tool's `build-docker` stops hand-enumerating
   targets; its pipeline derives from its manifest.
3. New reusables `mirror.yml` (login + `uv run mirror`, no inputs) and `build.yml` (getter +
   fanout as above, matrix values env-indirected in the `run:` line).

`publish-compose` stays local in placeframe (one consumer; compose publication is being
redesigned anyway — reevaluate after that refactor).

### Phase 6 — fleet cutover (folds `ci-refresh-seed.md`)

Per-repo **atomic** cutover PR: rewrite `integrate.yml`/`merge-gate.yml` to the shapes below,
bump every release-devkit `uses:` SHA and the wrapper's `RELEASE_DEVKIT_COMMIT` to one fresh
SHA in the same commit, and bring `release.yml` to trim-lint conformance (the `zizmor-audit`
D-items: checkout wrapper, scoped mint spelling, env-indirection) — its inline verbs and
wrapper install are untouched by this migration. Old files + old pin stay mutually consistent
until the switch; the new lint never sees old grammar. The fleet is currently diverged (bare
`prerelease`/`release` verbs, dual-trigger merge-gates, inline `create-github-app-token`,
direct `actions/checkout@v5`) — cutover jumps directly from diverged state to the new shape;
there is no intermediate re-convergence onto the trim grammar. Devkit repos merge and are
pushed first (pins must exist on the remote before consumer CI runs). Sequencing: Phase 2
pilot `bashrun` (exercises verify + merge-gate only) after Phase 1; Phase 5 pilot
`placeframe-capture-tool` (exercises verify+app-name, unity build, docker mirror+build,
draft) after Phases 3–4; then the sweep, roughly: simple publishers (python-devkit,
ci-devkit, logger-conf, openapi-client-codegen, pydantic-settings-pulumi, lbe-toolkit,
docker-devkit, unity-devkit), the infra trio (verify + merge-gate only), the app repos
(Make-it-Sing, Nessle, ObserveThing, StatefulUnity), placeframe last (most local surface).
placeframe additionally keeps `get-docker-matrix`-consuming local docker legs until Phase 4's
matrix covers them; `publish-compose` local permanently.

## Consumer end-state

Simple publisher (e.g. bashrun) — `integrate.yml` is `verify` (uses) + local `preflight`
(`needs: [verify]`) + `update-pr-draft-release` (uses, `needs: [preflight]`); `merge-gate.yml`
is triggers + concurrency + one gated `uses:` call.

placeframe-capture-tool `integrate.yml` (canonical example — this is the target spec; the
formatting is the established fleet style, which the migration does not change: blank lines
between jobs and top-level keys, permissions and secrets as block maps, never inline flow
maps):

```yaml
name: Integrate

on:
  workflow_dispatch:
  pull_request:
    branches: [dev]

concurrency:
  group: integrate-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  verify:
    uses: outernet-foundation/release-devkit/.github/workflows/verify.yml@<sha>
    with:
      app-name: capture-tool

  mirror-images:
    uses: outernet-foundation/docker-devkit/.github/workflows/mirror.yml@<sha>
    permissions:
      contents: read
      packages: write

  preflight:
    needs: [verify, mirror-images]
    # local: checkout PR-head + saver setup-uv + preflight-python + openapi --check

  build-unity:
    needs: [preflight, verify]
    permissions:
      contents: read
      packages: write
    uses: outernet-foundation/unity-devkit/.github/workflows/build.yml@<sha>
    with:
      version: ${{ needs.verify.outputs.version }}
    secrets:
      unity-email: …
      unity-password: …
      unity-serial: …

  build-docker:
    needs: [preflight, verify, mirror-images]
    permissions:
      contents: read
      packages: write
    uses: outernet-foundation/docker-devkit/.github/workflows/build.yml@<sha>

  update-pr-draft-release:
    needs: [build-unity, build-docker]
    uses: outernet-foundation/release-devkit/.github/workflows/update-pr-draft-release.yml@<sha>
    permissions:
      contents: read
      packages: read
```

placeframe: same skeleton plus local `preflight` (composed battery), local `build-docker` /
`publish-compose` legs (repo-owned scripts; `build.yml` replaces the getter + wrapper once
Phase 4 lands), unity `compile-check.yml` call, `update-pr-draft-release` needing
`publish-compose` + the unity fanout. What stays local everywhere is an ownership boundary,
not a mechanics one: repo-composed preflights, repo-owned scripts, `publish-compose`.

## lint-workflows disposition

| Concern | Disposition |
|---|---|
| actionlint + zizmor layers | unchanged; devkit-owned reusable files are audited by each devkit's own `verify.yml` self-lint and by consumers' lint passes over their caller files |
| SHA pin law | **new**: every `uses:` ref to a devkit-owned workflow is a full 40-hex SHA; all refs to the same devkit repo in this repo carry the same SHA; wrapper `RELEASE_DEVKIT_COMMIT` equal (per Resolve-first #3); within-file YAML anchors on the `uses` scalar sanctioned where a devkit appears twice |
| Trigger/concurrency shape | survives: merge-gate `pull_request: [labeled]` to `dev`, no `workflow_run` anywhere; integrate PR-to-`dev` + dispatch, `integrate-` group cancel-in-progress; release push `[main, dev]`, `release-${{ github.ref }}` **no** cancel |
| `release.yml` contract | survives nearly intact: spec-table verb grammar, no-ref checkout law, lone `persist-credentials: true` exception (stable job's tag-fetching push checkout), tag-fetch law, nuget-key env law keyed off `release-devkit.yaml`, forbidden `environment:`, single-filename law, wrapper validation (release.yml is the wrapper's last customer) |
| Inline-delivery enforcement | **new**: `prerelease`/`release` jobs must remain inline run steps — reusable conversion is the forbidden move, linted as such |
| integrate/merge-gate verb grammar | **dies** (spec tables, invocation regex application, verb-installation, env-reference, tag-fetch for these files, job-gating contracts, wrapper validation beyond release.yml) |
| Local-job hygiene | survives scoped to remaining local jobs: checkout wrapper + ref law + `persist-credentials: false`, at most one cache-writing setup-uv per file, env-reference resolution |

## Out of scope (recorded, not planned)

- `publish-compose` centralization (revisit after the compose-publication refactor).
- Preflight reusables (python-devkit `preflight-python.yml`).
- Any change to `release.yml`'s inline delivery model; any org-level workflow mechanism.
- Renaming canonical workflow filenames (npm/nuget publisher bindings forbid it).
