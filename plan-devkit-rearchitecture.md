# Devkit rearchitecture — binding-layer consolidation, package split, fleet cutover

Status: drafted 2026-10-09 from the architecture session; consolidates and supersedes
`release-devkit-finish.md` (executed; its T_FINISH bookkeeping is moot — nothing pins a single
finish SHA anymore), `ci-refresh-seed.md` (folded into Phase 7), `zizmor-audit.md` (live gated
items folded here; facts-and-decisions residue folded into `todo/supply-chain-control.md`'s
appendix), and
`plan-reusable-workflow-migration.md` (subsumed). Session decisions below are binding for
execution sessions. Cadence: one session per PR where practical, each landing on `dev` via the
repo's own merge-gate; commit discipline per AGENTS-SHARED (prose and code in separate commits,
no trailers).

## Resolve first (next session starts here)

1. **Lint residue scope.** The gutted lint (see disposition table) keeps actionlint + zizmor +
   the SHA law plus three candidate residue checks: (a) inline-delivery law — delivery jobs must
   call the composite action, never a reusable workflow (the one check protecting trusted
   publishing; recommendation: keep); (b) release.yml concurrency no-cancel (the delivery mutex;
   recommendation: keep); (c) merge-gate wake shape — labeled-only, per-PR serializing group
   (arguably droppable: zizmor already bans `workflow_run` and the verb re-derives every
   precondition on any wake; the surviving failure mode is a racing double-merge.
   Recommendation: keep — it is cheap; drop it if taste says).
   Same item confirms `verify.yml` bundling: `lint-workflows` ∥ `validate-release-plan` as
   internal parallel jobs with the fail-fast `needs` contract internal, exporting
   `version`/`version-code`, optional `app-name` input (two separate reusables would re-open
   needs-contract drift).
2. **Execution scope of the next session.** Recommendation: Phase 1 (build-artifact-registry-
   devkit split + publish) alone — it is small and unblocks everything; Phase 2
   (github-actions-devkit) gets its own session(s). Pilots after Phase 2+3+4 exist on the
   remote.
3. **build-artifact-registry-devkit starting version line.** Recommendation: fresh `0.1` —
   a new distribution name needs no continuity with ci-devkit's line, and a fresh base dodges
   the poisoned ci-devkit `0.2.1` base entirely.

## The model: two layers, one seam

The `-devkit` suffix names two different kinds of repos, and every smell the session found was
a piece sitting on the wrong side of the seam. The test is one question: **does this code know
GitHub exists?**

- **Domain toolchains** — unity-devkit, docker-devkit, python-devkit (+ logger-conf,
  openapi-client-codegen, pydantic-settings-pulumi, lbe-toolkit as simple publishers): pure
  "how to build/test/mirror/publish-in-the-abstract X", meaningful from plain bash on a laptop,
  coupled by domain, PyPI-pinned via each consumer's `uv.lock`. Hard law: no ambient `GITHUB_*`
  reads, no `::` annotations, no `$GITHUB_OUTPUT` writes in domain code. Convention: verbs
  print neutral output (JSON leg lists, plain banners); decoration may detect the platform,
  logic never may.
- **The platform binding** — release-devkit renamed **github-actions-devkit** (plural, matching
  the product): everything that knows GitHub Actions exists. One repo, clone-pinned,
  dependency-of-nothing. Holds: all reusable workflows, the release composite, `lint-workflows`,
  the merge-gate bot, the release/delivery verbs (OIDC trusted publishing, Releases API,
  `GITHUB_REF` parsing are platform-bound), runner provisioning (absorbed `setup.py` +
  vendored `third-party/`), and the matrix-envelope helper. Its own `uv.lock` resolves
  `bashrun` + `build-artifact-registry-devkit` + pydantic/strictyaml/typer.
- **build-artifact-registry-devkit** — ci-devkit's surviving half, renamed to its job: registry
  primitives for pushing/pulling build artifacts, locally or remotely (`builds`, `cache`,
  `setup_oras`, `registry_auth`). Purely registry concerns; no presentation, no runner
  knowledge. ghcr is a registry choice passed as a parameter, not platform coupling.

Supporting laws:

- **Verbs are named for side effects, never execution context.** "ci" is a context; shelf/push
  is a side effect. `ci-build-unity` → `build-unity --shelf`; docker's `build --mode ci` →
  `build --push` (image push + digest manifest), with runner provisioning peeled to binding
  pre-steps.
- **Stable-CLI-API doctrine is fleet law**: script names and flags are public API for every
  devkit, not just the binding repo — structure (in github-actions-devkit) and code (in
  consumer locks) are pinned by different mechanisms, so the YAML's expected verb surface must
  not move silently.
- **Prose rule**: fleet docs retire bare "registry" — "package registry" for the publishing
  side (PyPI/npm/NuGet), "build-artifact registry" for the OCI artifact side. Existing adapter
  names (`NuGetRegistry` etc.) already follow the cargo-qualified pattern; only prose changes.
- **Fleet YAML formatting is retained, not reformed**: blank lines between jobs and top-level
  keys, permissions and secrets as block maps. The migration changes structure, not style.
- D5 stands permanently: **no GitHub merge queues** — they land merge-group trees, never the
  certified PR head. D4 stands: keep actionlint; reassess only if upstream stalls on `$/`.

## Binding decisions (operator, 2026-10-09 session)

- All reusable workflows (verify, update-pr-draft-release, merge-gate, unity
  build/compile-check, docker build/mirror) live in github-actions-devkit. release-devkit is
  renamed github-actions-devkit. Pinning stays lint-enforced multi-spelling (literal `@<full-
  sha>` at every call site; routers/dispatcher muxes and generated pins were designed and
  rejected).
- release.yml delivery jobs get a devkit-owned **composite action** (trusted publishing binds
  repo + workflow filename; composite steps run inside the caller's job, so `job_workflow_ref`
  keeps naming the consumer's `release.yml` — warehouse#11096 blocks reusable workflows only).
  The per-consumer `setup-release-devkit` wrapper and `RELEASE_DEVKIT_COMMIT` die fleet-wide.
- ci-devkit splits as above; **`ci_step` is killed entirely** — its features are digestion of
  data the platform UI already holds (native step grouping/timing/failure marking, per-line
  timestamps); plain print banners replace it everywhere. ~12 call sites, mechanical.
- Matrix verbs emit **bare leg lists** (no `{'include': …}` envelope, no `matrix=` output
  spelling); the binding composes the GHA envelope and `$GITHUB_OUTPUT` transport via a helper
  verb, which is also the one place to guard the empty-legs case (the `fromJson('')`
  render-time footgun). The leg schema (which keys a leg carries) is named contract.
- `free_disk_space` and friends are runner provisioning owned by the binding layer (reusable
  inputs / pre-steps), not `docker-devkit.yaml` keys.
- Filenames inside the one repo disambiguate: `build-unity.yml` / `build-docker.yml` (job names
  `build-unity` / `build-docker`); `mirror.yml`, `compile-check-unity.yml` as named.
- `publish-compose` stays local in placeframe permanently (one consumer; being redesigned).
- The fleet jumps from diverged state directly to the new shape; there is no intermediate
  re-convergence onto the trim grammar.

## Verified platform mechanics (do not re-derive; researched 2026-10-09)

- **Composition is job-level.** A caller workflow mixes local jobs and `uses:` calls freely;
  `needs` wires across both. A calling job accepts only `needs`, `if`, `permissions`, `with`,
  `secrets`, `strategy`, `concurrency`, `name` — never `steps`, `runs-on`, `container`, `env`.
  Inside the called workflow everything is an ordinary workflow: multi-job graphs, internal
  `needs`, a getter job emitting output consumed by a fanout via
  `strategy.matrix: ${{ fromJson(needs.matrix.outputs.matrix) }}`, `container:` from matrix,
  `fail-fast`.
- **Self-checkout is first-class.** `job.workflow_repository` + `job.workflow_sha` give a called
  workflow its own resolved repo and SHA — `actions/checkout` with those checks the devkit out
  at exactly the pin the caller spelled. This is github-actions-devkit's install mechanism
  inside its reusables.
- **`uses:` is resolved statically by GitHub, server-side.** No expressions, no env, no
  filesystem. Cross-repo refs must be `owner/repo/.github/workflows/file.yml@ref`; `./` refs
  resolve same-repo at the caller's commit — github-actions-devkit's own `integrate.yml` calls
  its own reusables via `./` with no SHA and no self-pin bump. Consequence: a consumer's SHA is
  spelled only in the consumer's own files.
- **Same-org self-hosted runners work in called workflows** (callee uses the caller's runner
  pool); the org `unity` runners qualify. `github` context in the callee is the caller's event.
  Caller's `vars` are visible; secrets must be passed per call and forwarded explicitly at
  every nesting hop. `GITHUB_TOKEN` permissions propagate maintain-or-reduce.
- **Outputs chain** through `on.workflow_call.outputs` at each level.
- **Footguns.** `fromJson` on an empty string fails at render time. Nested-call limit is 10
  (this plan uses at most 2). Matrix-derived values interpolated into `run:` lines ride step
  `env` with the run line referencing the variable (zizmor template-injection remediation) —
  the standing law inside every devkit-owned file.

## To verify during Phase 2 / pilots (new mechanics, not yet verified)

- `github.action_ref` resolves to the called SHA inside a cross-repo composite action (the
  composite analogue of `job.workflow_sha`, enabling self-install); fallback is
  `github.action_path` off a root `action.yml` (the runner's archive download is the install).
- PyPI/npm/nuget trusted publishing accepts publishes through composite-wrapped steps
  (expected yes — identity binds to the job's workflow file; warehouse#11096 is about reusable
  workflows). Verified once in the bashrun pilot. **Fallback if rejected**: release.yml keeps
  inline verb steps; the release.yml half of the old verb-grammar lint revives; only the
  wrapper dies.
- actionlint does not lint composite `action.yml` internals; zizmor at the devkit root does
  cover them (the same reliance the current wrapper law makes). Composites must fail loudly on
  bad/empty inputs (actionlint cannot catch typo'd `with:` keys).
- actionlint 1.7.12 may not know the `job.*` context — verify against its release notes and
  bump the pin in the lint if needed (Phase 2).

## Phase 0 — land github-actions-devkit

The executed `release-devkit-finish.md` work sits on `github-actions-devkit` (renamed from
`lint-trim`), unlanded. **Defect to repair at landing**: the wrapper self-pin
`RELEASE_DEVKIT_COMMIT: f970dbb…` is orphaned (the branch was rebased after the audit sessions;
that SHA is an ancestor of neither HEAD nor origin/github-actions-devkit) — own CI's
lint/self-test jobs would fail their clone/checkout on a fresh runner. Re-pin to the landing HEAD in the same atomic commit as any workflow-spelling change,
push, land via merge-gate. The trim's own scope is otherwise complete and verified.

## Phase 1 — build-artifact-registry-devkit (the ci-devkit split)

- Split: `builds.py`, `cache.py`, `setup_oras.py`, `registry_auth.py` move to the new package
  (repo rename of ci-devkit); `install_oras`'s hardcoded `ensure_registry_login("ghcr.io")`
  becomes a parameter. Media-type strings rename to the new writer name safely (restore/pull
  don't filter on them; older manifests still pull).
- `ci_step.py` and `setup.py` (+ `third-party/dotnet-install.sh`) are deleted from the floor;
  setup's destination is github-actions-devkit's src (Phase 2), ci_step's destination is
  nowhere (banners replace it).
- Fresh `0.1` version line (Resolve-first #3); publish dev prerelease; the old ci-devkit
  distribution is frozen forever, **no yank** (broken stables precedent: uninstallable pins
  sink; resolvers move past).
- Its own repo CI keeps the hand-written shape at current pins until the Phase 7 sweep; keep
  the `tools/devkit` sidecar-lock discipline for python-devkit consumption.
- API breaks ship with the manually bumped `major_minor` per that repo's own release flow.
- AGENTS.md rewritten to the registry-primitives charter (ORAS lives only here; builds ≠
  caches; no runner knowledge — now true with no asterisks).

## Phase 2 — github-actions-devkit (rename + all binding surface)

- **Repo rename** release-devkit → github-actions-devkit. GitHub redirects old URLs (including
  `uses:` refs — the lint must enforce the canonical new spelling so the redirect can never
  mask a missed rename). Update clone URLs, `DEVKIT_REPOSITORY`, the self-test clone, AGENTS.md
  title/identity. The dependency-of-nothing law survives the rename unchanged.
- **Reusables**, each self-checking-out via `job.workflow_repository`/`job.workflow_sha`,
  third-party action SHAs pinned once here:
  - `verify.yml` — internal parallel `lint-workflows` + `validate-release-plan` (checkout
    PR-head ref law + full fetch internal); optional `app-name` input runs `get-app-version`
    internally and exports `version`/`version-code`.
  - `update-pr-draft-release.yml` — `release --channel pr`; `if: github.event.pull_request`
    internal; `packages: read` at call site; needs the consumer's terminal build legs.
  - `merge-gate.yml` — full-clone checkout of the PR head, internal mint of the merge-bot App
    token (`vars.MERGE_BOT_APP_ID` reads the caller's var; key arrives as named secret
    `merge-bot-private-key`), `merge-gate --head-sha`.
  - `build-unity.yml` / `compile-check-unity.yml` — matrix getter (piping the domain verb's
    bare leg list through the envelope helper) + fanout internally: `runs-on: [self-hosted,
    unity]`, `container: ${{ matrix.editor-image }}`, wipe-workspace, checkout + setup-uv
    restore, license `--license` threading, unity secrets named, registry auth ambient,
    runner-provisioning pre-steps (absorbed `setup`), `version` input from
    `needs.verify.outputs.version`, optional `project` scoping passthrough. Verb code resolves
    from the consumer's `uv.lock` — the `@sha` pins structure, the lock pins code.
  - `build-docker.yml` / `mirror.yml` — docker matrix getter + fanout, mirror login + `uv run
    mirror`; matrix values env-indirected in `run:` lines; `free_disk_space` a reusable input.
- **Release composite** `.github/actions/release` (inputs `channel`, `nuget`): absorbs the
  checkout/no-ref/tag-fetch law, setup-uv, nuget login (`NUGET_API_KEY` minted internally),
  and the verb invocation; self-installs per the to-verify mechanics above. Consumer
  release.yml collapses to triggers + concurrency + delivery jobs of one `uses:` each.
  Delivery jobs stay inline run-step jobs (composite = inline; reusable = forbidden).
- **Matrix envelope helper verb** — stdin leg list → `{"include": …}` envelope →
  `$GITHUB_OUTPUT`, with the empty-legs loud guard.
- **Lint gut** per the disposition table below; delete the integrate/merge-gate grammar, the
  verb spec tables, ref/tag-fetch/verb-installation/env-reference/wrapper validation, the
  one-saver-cache rule, the nuget-key env law (`declares_nuget()` dies with it — content
  validation already lives in pydantic config load and `validate-release-plan`), and the
  `environment:` ban. Add the SHA law and the residue per Resolve-first #1.
- Own `integrate.yml`/`merge-gate.yml` cut over to `./` calls (no self-pin). The self-test
  survives: dynamic clone at PR head, `validate-release-plan` + `merge-gate --dry-run` with
  cwd = this checkout.
- Kill `ci_step` imports in own verbs → plain banners; absorb `setup.py` + `third-party/`.
- Relock onto `build-artifact-registry-devkit>=0.1` (+ bashrun 0.6 line when published).
- AGENTS.md rewritten spec-first in the same PR set (identity, installation section, commands'
  lint row, config's `build_reference` provenance — the sections the consolidation audit
  enumerated).

## Phase 3 — unity-devkit (domain purification + renames)

- `ci-build-unity` → `build-unity --shelf`; matrix verbs emit bare leg lists (the leg schema —
  `project`, `platform`, `editor-image`, `license`… — becomes named contract in its AGENTS.md;
  renaming a key breaks the binding's fanout YAML).
- Drop `ci_step` and `setup` imports: provisioning (configure_git, disk space, toolchain
  installs) moves to the reusable's pre-steps in github-actions-devkit; banners replace
  `ci_step`. Verbs assume a provisioned environment.
- `0.2` → `0.3` (`major_minor` bump carries the API breaks), publish dev prerelease.
- AGENTS.md "Consumer CI template" section replaced by the reusable reference; config-file law
  row for unity-devkit unchanged (JSON exception — read by C# inside Unity).

## Phase 4 — docker-devkit

- Absorb the CI shim into the build path with **explicit parameters** (registry, actor, token
  supplied by the binding — no ambient `GITHUB_*` reads in domain code): `build --push`
  replaces `build --mode ci`; deletes placeframe's 53-line `ci/build_docker.py` wrapper;
  capture-tool's workflow-level QEMU/buildx/login steps die the same way (QEMU arm64 stays one
  setup step inside the reusable).
- `docker-build-matrix` learns the cross-compile cohort (`x-cross-compile-targets`,
  platform-pinned services, `platform` facts from manifest `platforms:` keys) and emits bare
  leg lists; capture-tool's `build-docker` stops hand-enumerating targets.
- Drop `ci_step`. `0.2` → `0.3`, publish dev prerelease.

## Phase 5 — python-devkit

- Drop `ci_step` (banners in preflight); retarget or drop the ci-devkit dependency (audit
  actual usage at execution — if only `ci_step`, the floor dependency dissolves entirely).
- Land the `deptry-src` fix (`deptry .` → `deptry src`; repo-root scans misclassify absolute
  self-imports as transitive DEP003) — every consumer's relock onto this line closes its
  deptry red window.
- `0.2` → `0.3`, publish dev prerelease.

## Phase 6 — pilots

- **bashrun** after Phase 2: exercises verify + merge-gate + the release composite; carries
  the PyPI-through-composite verification gate (fallback decision point for release.yml).
- **placeframe-capture-tool** after Phases 3–4: exercises verify+app-name, unity build,
  docker mirror+build, update-pr-draft-release.

## Phase 7 — fleet sweep (folds ci-refresh-seed; the old doc's mechanics re-aimed from
"wrapper re-pin + grammar rewrite" to "atomic cutover to reusables/composite + SHA bump")

**Registry state (verified 2026-10-08; re-verify anything load-bearing).** Stables: bashrun
0.3.0, ci-devkit 0.2.0 (frozen), docker-devkit 0.2.0, logger-conf 0.2.0,
openapi-client-codegen 0.2.0, python-devkit 0.2.0, unity-devkit 0.1.25,
pydantic-settings-pulumi 0.1.2. Dev prereleases: bashrun `0.5.0.dev37693327146` and ci-devkit
`0.2.1.dev37711169350` (old run-keyed; the ci-devkit one is this repo's current floor),
docker-devkit `0.2.1.dev109`, unity-devkit `0.2.0.dev215` (count-keyed). npm:
`org.outernet.playerbuild` 0.1.5, `org.outernet.lbetoolkit` 1.0.0, `.livekit`/`.photon` at
`0.0.0-local` (first new-paradigm publish = 1.0.x). **Poisoned bases** (run-id prereleases make
the base uninstallable): docker-devkit 0.2.1, bashrun 0.5.0, ci-devkit 0.2.1,
pydantic-settings-pulumi 0.2.0 — resolution is the major_minor sweep. **Broken stables**:
docker-devkit 0.2.0 and unity-devkit 0.1.24 pin a nonexistent ci-devkit prerelease —
uninstallable; decision: no yank. PEP 440 `.devN` compares numerically: run-id-keyed floors die
on the first count-keyed publish; Make-it-Sing's exact `docker-devkit==0.2.1.dev37485576216`
already excludes the count-keyed line.

**Bump table (re-derived for the split).** build-artifact-registry-devkit `0.1` (new name,
fresh line). bashrun `0.5` → `0.6` (retires the poisoned never-stable 0.5). python-devkit,
docker-devkit, unity-devkit (+ `org.outernet.playerbuild`), logger-conf,
openapi-client-codegen, pydantic-settings-pulumi: `0.2` → `0.3` (unity/docker rows carry the
API breaks). placeframe's 8 packages +1 minor each (api-client 0.1→0.2; core/arfoundation/
magicleap 1.0→1.1; auth/logging/common/core-python 0.1→0.2). lbe-toolkit 1.0 → 1.1 (all three
packages). App entries NOT bumped (not registry-consumed).

**Per-repo cutover (atomic per repo):** rewrite `integrate.yml`/`merge-gate.yml` to the
consumer end-state shapes, rewrite `release.yml` to composite calls (fallback grammar if the
pilot rejected composites), bump every `uses:` SHA to one fresh github-actions-devkit SHA and
relock onto the bumped floors — all in the same commit; old files + old pins stay mutually
consistent until the switch. Local-job hygiene survives scoped to remaining local jobs
(checkout wrapper + PR-head ref + `persist-credentials: false`, one cache-writing setup-uv per
file).

**Sequencing laws.** Prereleases must exist on the registry before downstream relocks reference
them; devkit repos merge and are pushed first (pins must exist on the remote before consumer CI
runs); one repo = one PR landing via its own merge-gate; the sweep deliberately does NOT
promote to stable (promotions happen naturally later; green sweep then promote `dev` → `main`
where receivers live on the default branch); update stale agent docs alongside code.

**Sweep order.** Devkit self-cutovers first (build-artifact-registry-devkit,
github-actions-devkit's own files beyond `./` refs — none needed, python/docker/unity/devkit
repos themselves), then simple publishers (logger-conf, openapi-client-codegen,
pydantic-settings-pulumi, lbe-toolkit), the infra trio (verify + merge-gate only), app repos
(Make-it-Sing, Nessle, ObserveThing, StatefulUnity), placeframe-capture-tool is the Phase 6
pilot, placeframe last (most local surface).

**Per-repo specifics (from reconnaissance; mechanics re-aimed).** placeframe: 8×
`registries:`→`registry:`+`identity:`, drop `ci_workflow:`, `built_images: true` confirmed,
mirror-images precedes preflight (postgres FROM mirror-pinned base), `.github/workflows/
AGENTS.md` documents the OLD contract — prose update is load-bearing, `cesium.yml`
dispatch-only gets signature checks + wrapper-conformant checkouts; its in-flight
`more-ci-fixes` branch (pin→ed406a0) folds or is superseded; placeframe additionally keeps
`get-docker-matrix`-consuming local docker legs until Phase 4's matrix covers them, and
`publish-compose` local permanently. Make-it-Sing: landing strategy ci-support-redux → new
shape → green → merge-gate → evergreen `dev`; `built_images: true` confirmed
(`build-livekit-token`); replace exact docker-devkit pin with `>=` floor; repo-local
`build-livekit-token`/`build-docker` jobs fine. lbe-toolkit: build on ci-support-redux, 1.0→1.1
all three packages, delete legacy `publish-config.json`, npm identities
`org.outernet.lbetoolkit[.livekit|.photon]`, then retire old ci.yml/release.yml.
placeframe-capture-tool: app `builds` dict→list, add `update-pr-draft-release`, adopt new-line
UPM pins (verify consumed set), supersede stale local branches. Infra trio: non-publishing
(integrate + merge-gate only); canonicalize preflight onto `uv run preflight-python` (adds
python-devkit dev-dep, follows python-devkit's new line); infra-github-org owns the
`evergreen-dev` ruleset + merge-bot App + `UNITY_*` wiring; **dirty tree warning:
infra-github-org `src/stacks/dev.py` was modified at reconnaissance time — inspect before
committing there**.

**pyproject hygiene, every repo, every in-tree pyproject.** Delete deptry
`known_first_party` self-declarations (instance: placeframe `build/pyproject.toml`;
`per_rule_ignores` tables stay; red windows close at each repo's relock onto python-devkit's
fixed line — release-devkit is in that window from github-actions-devkit on). Delete `[tool.uv]
prerelease = "if-necessary-or-explicit"` (uv 0.12 deprecates; drop the table when it's the
only key). Delete redundant hatch wheel `include` blocks naming files under `packages`
(instance here: this repo's own `pyproject.toml` wheel includes for `py.typed`/`zizmor.yaml`;
placeframe datamodels uses `force-include` — inspect and drop the same way).

**Standing constraints.** The GitHub App token cannot push or merge — lands go through each
repo's merge-gate or the operator. **Never label a PR in a repo without a live verification
job** (vacuously-true all-green) — lbe-toolkit and Make-it-Sing must not see `ready-to-merge`
before integrate runs.

**Operator-owned prerequisites.** evergreen-dev ruleset membership for Make-it-Sing +
lbe-toolkit; `MERGE_BOT_APP_ID` var + `MERGE_BOT_APP_PRIVATE_KEY` secret per repo; `UNITY_*`
secrets; npm trusted-publisher rows for the three `org.outernet.lbetoolkit*` names bound to
`release.yml`. The agent verifies wiring exists before labeling; it does not prepare the
ruleset PR.

## Consumer end-state

Simple publisher (e.g. bashrun) — `integrate.yml` is `verify` (uses) + local `preflight`
(`needs: [verify]`) + `update-pr-draft-release` (uses, `needs: [preflight]`); `merge-gate.yml`
is triggers + concurrency + one gated `uses:` call; `release.yml` is triggers + concurrency +
delivery jobs of one composite `uses:` each.

placeframe-capture-tool `integrate.yml` (canonical example — the target spec; formatting is
the established fleet style, which the migration does not change; job key order: `needs`,
`permissions`, `uses`, `with`, `secrets`):

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
    uses: outernet-foundation/github-actions-devkit/.github/workflows/verify.yml@<sha>
    with:
      app-name: capture-tool

  mirror-images:
    permissions:
      contents: read
      packages: write
    uses: outernet-foundation/github-actions-devkit/.github/workflows/mirror.yml@<sha>

  preflight:
    needs: [verify, mirror-images]
    # local: checkout PR-head + saver setup-uv + preflight-python + openapi --check

  build-unity:
    needs: [preflight, verify]
    permissions:
      contents: read
      packages: write
    uses: outernet-foundation/github-actions-devkit/.github/workflows/build-unity.yml@<sha>
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
    uses: outernet-foundation/github-actions-devkit/.github/workflows/build-docker.yml@<sha>

  update-pr-draft-release:
    needs: [build-unity, build-docker]
    permissions:
      contents: read
      packages: read
    uses: outernet-foundation/github-actions-devkit/.github/workflows/update-pr-draft-release.yml@<sha>
```

placeframe: same skeleton plus local `preflight` (composed battery), local `build-docker` /
`publish-compose` legs (repo-owned scripts; `build-docker.yml` replaces the getter + wrapper
once Phase 4 lands), unity `compile-check-unity.yml` call, `update-pr-draft-release` needing
`publish-compose` + the unity fanout. What stays local everywhere is an ownership boundary,
not a mechanics one: repo-composed preflights, repo-owned scripts, `publish-compose`.

## lint-workflows disposition

Philosophy carried from the executed trim: found-file model, no presence checks (accepted
hole: renaming a canonical file dodges its contract — self-inflicted, accepted); taste is not
lint; misordering fails loudly at runtime. The single-copy artifacts make most of the old
surface structurally impossible to drift, so the lint shrinks to:

| Concern | Disposition |
|---|---|
| actionlint + zizmor layers | unchanged; devkit-owned files audited by the devkit's own self-lint; composite internals zizmor-covered at the devkit root, actionlint-blind (composites fail loudly on bad inputs instead) |
| SHA pin law | **the core check**: every `uses:` ref to github-actions-devkit (workflow or action) is a full 40-hex SHA; all refs to it in one repo carry the same SHA; the canonical repo name is enforced (GitHub's rename redirect must never mask a stale spelling); within-file YAML anchors on the `uses` scalar sanctioned |
| Inline-delivery law | delivery jobs must be inline jobs calling the composite action — never a reusable workflow (Resolve-first #1a) |
| release.yml concurrency | `release-${{ github.ref }}`, no cancel — the delivery mutex (Resolve-first #1b) |
| merge-gate wake shape | labeled-only wake, per-PR serializing group (Resolve-first #1c) |
| integrate/merge-gate grammar, verb spec tables, ref/tag-fetch laws, verb-installation, env-reference resolution, wrapper validation, one-saver-cache, nuget-key env law + `declares_nuget()`, `environment:` ban | **die** — absorbed by single-copy reusables/composite (cannot drift), already actionlint/zizmor territory, or moot with the wrapper's death |

## Out of scope (recorded, not planned)

- Preflight reusables (python-devkit `preflight-python.yml` as a github-actions-devkit
  reusable) — follow-up phase.
- The `$/` flip (call sites + lint constants + tests + delete the self-repository zizmor
  stanza, one change): gated on an actionlint release accepting `$/` and runner fleet ≥
  2.336.0 (verify the self-hosted fleet version first). Scope much reduced by this
  rearchitecture — it now matters only for consumers' local-job wrappers (checkout/setup-uv);
  github-actions-devkit itself pins third-party actions directly inside its files.
- Supply-chain initiative — parked at `todo/supply-chain-control.md` (resume after Phase 7
  cutover; its stale pointers were updated during consolidation). Not adopted there:
  fleet-wide `--min-severity medium`.
- Hotfix release model — parked at `todo/hotfix-release-model.md`.
- Path-diff change-detection bug (build inputs outside a package's declared `path` are
  invisible) — parked at `todo/CRITICAL-BUG.md`.
- Any change to release.yml's inline delivery model beyond the composite; any org-level
  workflow mechanism; renaming canonical workflow filenames (npm/nuget publisher bindings
  forbid it).
