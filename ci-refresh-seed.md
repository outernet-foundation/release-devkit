# CI Refresh Seed — fleet-wide CI paradigm migration, pin updates, relock, green

Status: reconnaissance complete (2026-10-08; registry state verified live). Operator decisions
recorded below are binding for the execution sessions. Verify anything that smells before
betting a session on it.

**Prerequisite:** complete `release-devkit-finish.md` FIRST — the lint trim, found-file
model, zizmor adoption, self-lint, and self-landing pair-bump all land there. Wherever
`84afa7a…` appears below, read **T_FINISH** — the final SHA recorded in that doc once its
PR-2 lands. The trimmed lint only loosens (style rules and presence checks deleted); the
canonical file shapes below are unchanged and remain what migrating repos copy.

**Retarget (2026-10-09, zizmor-audit item-1 session):** the target shape below is SUPERSEDED
in two places — every third-party `uses:` becomes the repo's per-repo composite wrapper
(`.github/actions/{checkout,setup-uv,mint-token,nuget-login}`, SHA-pinned upstreams inside;
see release-devkit's own `.github/actions/` and its AGENTS.md), and merge-gate.yml wakes on
the `ready-to-merge` label ALONE (no `workflow_run`; single-payload
`pull_request.head.sha` spellings; mint step = the mint-token wrapper). The doc's Gen-4 tables
below describe the pre-wrapper shape; **release-devkit@`lint-trim`'s own files are the
reference to copy from** until docker-devkit/unity-devkit flip at their sweep steps (each
consumer's file change + re-pin land as one atomic commit per repo — pre-sweep consumers
intentionally redden under the new lint). Unity repos additionally env-indirect the two
tainted shapes (`--project`, `--license`) per D7.

## The goal, restated

1. Every repo with CI runs the **new CI paradigm** against the **latest release-devkit dev tip**
   — T_FINISH, the final SHA of `release-devkit-finish.md` (at seed time that tip was
   `84afa7a39ba21ab8971014dbefe130e3b9df8ded`, "Fix bugs").
2. Every published package gets a **`major_minor` bump** and publishes a clean-line dev
   prerelease; every consuming repo re-pins (`>=` floor onto the new line) and **relocks** —
   one full **DAG sweep, root → tip** (see Decisions).
3. All repos' CI is **green**.

## Decisions (operator, 2026-10-08)

- **Pin policy: `>=` floors, never `==`.** The committed `uv.lock` is the exact pin; floors
  only shape re-resolution. Floors must name a stable or count-keyed prerelease — never a
  run-id-keyed one (see semantics section for why).
- **Full DAG `major_minor` sweep.** Bump the package's `major_minor`, land, publish the new
  line's dev prerelease, then bump every consuming repo's floor and relock — strictly
  sequentially from the DAG root to the tip. Acknowledged as time-consuming and partly
  redundant, chosen as the safest option; release-devkit iteration is nearly done, so this is
   expected to be the last such sweep. This also un-poisons every run-id-keyed dev base (the new
   line starts in a fresh base) and sidesteps the broken docker-devkit 0.2.0 / unity-devkit
   0.1.24 stables entirely (floors move past them).
- **release-devkit itself: planned in `release-devkit-finish.md`, which executes before this
  sweep.** Binding decisions live there — found-file lint model (no presence checks, no repo
  taxonomy), style rules deleted, zizmor adopted alongside actionlint, spec↔CLI sync test,
  self-lint at own pin, static self-pin pair-bump (`ad42152` → post-trim tip +
  `--head-sha` flip as one atomic commit), `merge-gate --dry-run` exercised by the self-test.
  Nothing in this sweep touches release-devkit except the `ci-devkit` floor re-base riding
  step 2. This sweep pins T_FINISH (that doc's final SHA) everywhere it previously pinned
  `84afa7a`.

## The target shape (Gen 4, as enforced by `lint-workflows` at pin `84afa7a`)

Reference implementations to copy from: **docker-devkit** and **unity-devkit** on `dev` — they are
the only two repos at the latest pin with the full new shape. Where prose and lint disagree, the
lint wins (`release-devkit/AGENTS.md`).

Four files:

- `.github/workflows/integrate.yml` — PR-to-`dev` + dispatch. Jobs:
  `lint-workflows` (parallel root) ∥ `validate-release-plan` (parallel root, publishing repos) ∥
  `mirror-images` (parallel root, repos with mirrored images) → `preflight` (needs
  `[lint-workflows, mirror-images?]`; owns the file's ONE cache-writing setup-uv) → repo-specific
  legs. Publishing repos MUST also run `update-pr-draft-release` (gated
  `if: github.event.pull_request`, needs `validate-release-plan` + shelf-pushing build legs,
  verb `release --channel pr`). File-level YAML anchors `&checkout` / `&uv-restore` /
  `&setup-release-devkit` on all repeated steps.
- `.github/workflows/release.yml` — push to `main`+`dev`; concurrency `release-${{ github.ref }}`
  with NO cancel. Jobs: `prerelease` (`release --channel dev`) and `release`
  (`release --channel stable`). **Never rename this file** (npm/nuget trusted publishers bind to
  the workflow filename).
- `.github/workflows/merge-gate.yml` — PR `labeled` + `workflow_run` from Integrate completed.
  Verb line MUST be `merge-gate --head-sha ${{ github.event.pull_request.head.sha || github.event.workflow_run.head_sha }}`
  (lint regex `^ --head-sha .+$`; the old no-arg spelling and the old `HEAD_SHA` env-var spelling
  both fail lint). Mint step `actions/create-github-app-token@v3` (id `mint`, `app-id` spelling)
  between wrapper and verb; `GITHUB_TOKEN: ${{ steps.mint.outputs.token }}` on the verb env.
- `.github/actions/setup-release-devkit/action.yml` — one bash step, env
  `RELEASE_DEVKIT_COMMIT: 84afa7a39ba21ab8971014dbefe130e3b9df8ded`, two-line tokenless clone into
  `$RUNNER_TEMP/release-devkit`.

Verb spellings (lint-enforced, from `lint_workflows.py` `VERB_SPECS` / `RELEASE_CHANNELS`):

| Old (fails lint at `84afa7a`) | New |
|---|---|
| `prerelease` / `publish-prerelease` job running verb `prerelease` or `publish-prerelease` | job `prerelease` running `release --channel dev` |
| `release` job running bare `release` | job `release` running `release --channel stable` |
| `update-pr-draft-release --pr-number … --run-number …` | job `update-pr-draft-release` running `release --channel pr` (no flags) |
| `merge-gate` (no args) | `merge-gate --head-sha ${{ … }}` (flag, not env) |

`release-devkit.yaml` schema — current model (`config.py`, `extra="forbid"`, hard flips):

| Old key | Migration |
|---|---|
| root `ci_workflow:` | delete (field removed) |
| package `registries: {pypi: name}` | `registry: pypi` + `identity: name` |
| app `builds: {registry: …, artifacts: [{…, name: …}]}` | `builds:` = list of `{project, platform, file}` (no `registry`, no `name` — shelf address is derived from `GITHUB_REPOSITORY`; release asset name comes from `file`) |
| (absent) | `built_images: true` where CI builds images and shelves the digest manifest |

Landing model: bors. PR to `dev` → integrate green → label `ready-to-merge` → merge-gate
`--no-ff` merges, deletes branch, deletes `pr-{N}` draft. The `workflow_run` green wake is inert
until `merge-gate.yml` reaches `main` (the receiver is read from the default branch) — so repos
whose `main` is stale get only the label wake until their next stable promotion.

## The devkit dependency DAG

```
bashrun ──> ci-devkit ──> python-devkit
                │              │
                ├──> docker-devkit (also: python-devkit)
                ├──> unity-devkit (pkg also: ci-devkit)
                └──> release-devkit (also: python-devkit, ci-devkit; NOT on PyPI — SHA-pinned)

Consumers:
  logger-conf          (dev group: python-devkit)
  openapi-clientgen    (deps: bashrun; dev: python-devkit)
  pydantic-settings-pulumi (dev: python-devkit)
  placeframe           (dev: unity-devkit, docker-devkit, python-devkit, logger-conf, openapi-client-codegen)
  placeframe-capture-tool (dev: same set as placeframe)
  Make-it-Sing         (dev: bashrun, docker-devkit, python-devkit, unity-devkit)
  lbe-toolkit          (dev: unity-devkit)
  infra trio           (no devkit deps)
```

Latest stable tags (local): bashrun 0.3.0 (2026.10.3), ci-devkit 0.2.0, docker-devkit 0.2.0,
logger-conf 0.2.0, openapi-client-codegen 0.2.0, python-devkit 0.2.0, unity-devkit 0.1.25
(all 2026.10.2), pydantic-settings-pulumi 0.1.2 (2026.10.3). release-devkit: never published,
consumed by commit SHA. Dev prereleases (`{base}.dev{count}` / `-dev.{count}`) are published by
`release --channel dev` on each dev merge.

**Registry state (verified live this session, PyPI + npm JSON APIs):** dev prereleases exist and
are current wherever `dev` is ahead — bashrun `0.5.0.dev37693327146` (Oct 7, old run-keyed
spelling), ci-devkit `0.2.1.dev37711169350` (Oct 8, old spelling — exactly the floor
release-devkit declares), docker-devkit `0.2.1.dev109` and unity-devkit `0.2.0.dev215` (both
Oct 8, **new count-keyed spelling** — verified against `git rev-list --count`: 110/216 at tip,
one merge short), pydantic-settings-pulumi `0.2.0.dev37277781492` (Oct 5). Where dev==main
(python-devkit, logger-conf, openapi-client-codegen) the Oct-5 prereleases are superseded by
stable 0.2.0 — **the stable IS the newest artifact** for those three. Under the sweep this is
moot (all lines move), but it means nothing blocks on registry availability: today's artifacts
already satisfy any intermediate relock.

npm: `org.outernet.playerbuild` latest 0.1.5, no dev prereleases ever (path-diff gating — the
npm package only publishes when its path changes). `org.outernet.lbetoolkit` 1.0.0 stable
exists; `.livekit` / `.photon` are stuck at `0.0.0-local` (sentinel-shaped broken publish
history) — their first publish under the new paradigm will be 1.0.x.

**Version-spelling gotcha (PEP 440 `.devN` compares numerically):** once a package's next
prerelease is count-keyed (small N), old run-keyed pins/floors become unsatisfiable —
release-devkit's `ci-devkit>=0.2.1.dev37711169350` floor dies the moment ci-devkit publishes a
count-keyed `0.2.1.dev<N>` (any small N < 37711169350), and Make-it-Sing's exact
`docker-devkit==0.2.1.dev37485576216` already excludes the existing `0.2.1.dev109`. Both
re-pins are mandatory parts of their sweep steps, not judgment calls.

**Prerelease resolution semantics (verified live with uv against PyPI):**
- Prereleases are invisible to floors that don't name one: `docker-devkit>=0.2.1` is
  *unsatisfiable* while only `0.2.1.dev*` exist; `>=0.1.19` resolves to stable 0.1.23, never a
  newer prerelease.
- A floor naming a prerelease (e.g. `>=0.3.0.dev110`) is the per-requirement opt-in, and the
  resolver then picks the numerically highest eligible across all bases — floors don't bound
  above, the lockfile does. `uv lock` / `uv lock --upgrade-package <name>` re-resolve;
  `--locked` installs exactly the locked version.
- Run-id-keyed prereleases permanently outrank count-keyed ones in the same base (verified:
  floor `docker-devkit>=0.2.1.dev109` resolves to the old-lineage `0.2.1.dev37490360141`, not
  the count-keyed Oct-8 build). Poisoned bases: docker-devkit 0.2.1, bashrun 0.5.0, ci-devkit
  0.2.1, pydantic-settings-pulumi 0.2.0. Resolution: **major_minor sweep** (Decisions).

**Broken published stables (verified from PyPI metadata):** docker-devkit **0.2.0** and
unity-devkit **0.1.24** carry an exact dangling pin `ci-devkit==0.1.15.dev36756330648` (a
nonexistent version) — both are uninstallable and resolvers silently sink past them (why
placeframe's lock sits at docker-devkit 0.1.23). PyPI versions are immutable; the sweep's
floors move consumers past them without needing republishes. **Decision: no yank** — they may
be yanked later at the operator's discretion; harmless to leave for now.

## CI generation per repo + most up-to-date CI branch

The user's question answered: which branch carries the freshest CI *files*, per repo.

| Repo | CI branch to build on | Current checkout | Gen | r-d pin | Notes |
|---|---|---|---|---|---|
| docker-devkit | `dev` | `dev` | **4** | `84afa7a` | reference repo |
| unity-devkit | `dev` | `dev` | **4** | `84afa7a` | reference repo |
| Make-it-Sing | `ci-support-redux` | `ci-support-redux` | 3.5 | `28c8cd2` | has update-pr-draft-release but OLD verb form; `dev` branch is still Gen-1 ci.yml |
| bashrun | `dev` | `dev` | 3 | `029a9a6` | |
| ci-devkit | `dev` | `dev` | 3 | `029a9a6` | |
| placeframe | `dev` | `dev` | 3 | `029a9a6` | local `more-ci-fixes` branch is 5 commits ahead (pin→`ed406a0` + Unity pkg fixes) — in-flight, reconcile |
| placeframe-capture-tool | `dev` | `dev` | 3 | `029a9a6` | |
| infra-github-org | `dev` | `dev` | 3-infra | `029a9a6` | non-publishing (no release.yml), no `&setup-release-devkit` anchor, merge-gate lacks `--head-sha` |
| infra-github-runners | `dev` | `dev` | 3-infra | `029a9a6` | same |
| infra-rathole | `dev` | `dev` | 3-infra | `029a9a6` | same |
| lbe-toolkit | `ci-support-redux` | `main` (Gen-1) | 3 | `029a9a6` | `main`/`dev` still run old ci.yml+release.yml (`uvx release-devkit==0.1.10`); `release-devkit.yaml` on ci-support-redux uses old `registries:` schema; npm identities confirmed `org.outernet.lbetoolkit*` |
| logger-conf | `dev` (== `main`) | `main` | 2 | `1130b98` | job `publish-prerelease`; old config schema |
| openapi-clientgen | `dev` (== `main`) | `main` | 2 | `1130b98` | same |
| python-devkit | `dev` (== `main`) | `main` | 2 | `1130b98` | same |
| pydantic-settings-pulumi | `dev` | `dev` | 2 | `1130b98` | same |
| release-devkit | `dev` | `dev` | self | `ad42152` | lint trim + self-lint + self-landing planned in `release-devkit-finish.md` (executes first; final SHA = T_FINISH); sweep remainder: `ci-devkit` floor re-base (devkit chain step 1) |

No CI at all (out of scope unless told otherwise): code-workspace, infra, neutron, pulsar,
second-brain-secure; `misc/` is not a git repo.

Release-devkit pin ladder (old → new): `1130b98` < `029a9a6` < `ed406a0` < `28c8cd2` < `84afa7a`.
Stale working branches (content already merged via PRs, safe to ignore): docker-devkit
`loosen-ci-devkit-pin` / `persist-bake-manifest`, `origin/update-release-devkit` on several repos.
Dirty working trees are all trivial local noise (slnx, .vscode, dotnet-install.sh, placeframe
`Assets/Packages.meta` untracked, infra-github-org `src/stacks/dev.py` modified — inspect before
committing anything in that repo).

## Per-repo migration checklists

Common Gen-3→4 items (apply to every Gen 2/3 repo; full detail in "Target shape"): bump wrapper
pin to `84afa7a`; release.yml verbs → `--channel` spellings; merge-gate → `--head-sha` flag;
add/migrate `update-pr-draft-release` → `release --channel pr`; config schema migration; plus
the sweep items from the Work plan (own `major_minor` bump, floors onto upstream new lines,
relock). "Floor" always means `>=` naming the upstream first new-line prerelease
(e.g. `bashrun>=0.6.0.dev{count}`) — the lock pins the exact version.

Two pyproject.toml line removals apply to every repo (Gen 4 and release-devkit included), every
`pyproject.toml` in each tree (workspace members included):

- Delete any `[tool.deptry] known_first_party` self-declaration (instance today: placeframe's
  `build/pyproject.toml`). deptry reddens on absolute self-imports until each repo's lock carries the
  step-3 python-devkit `deptry src` fix — the red window per repo closes at its relock,
  accepted by design (release-devkit itself is in that red window from `lint-trim` on).
  `per_rule_ignores` tables are genuine reviewed findings and stay (release-devkit carries
  none: zizmor is not a dependency there — the verb fetches it as a pinned, sha256-verified
  release binary, mirroring actionlint).
- Delete the `[tool.uv]` `prerelease = "if-necessary-or-explicit"` line (release-devkit's
  instance was dropped ahead of the sweep on `lint-trim`) — it redundantly spells uv ≤0.11's
  default, and uv 0.12+ demotes the value to a deprecated alias of `if-necessary` that will
  eventually fail to parse; drop the `[tool.uv]` table too when this was its only key.
- Delete the redundant `[tool.hatch.build.targets.wheel] include` blocks that name files
  already under the `packages` directory (bashrun, ci-devkit, docker-devkit, logger-conf,
  prepo, quarto-render, python-devkit, unity-devkit, openapi-client-codegen,
  pydantic-settings-pulumi, release-devkit, placeframe's common/core/neural-networks) —
  hatchling's `packages` selection ships every git-tracked file under the package dir
  (verified empirically in release-devkit and bashrun: `py.typed` and data files ship with
  no include block; every listed instance names only such files). The blocks came from a
  false constraint in bashrun's `AGENTS.md` (wheels "omit non-Python files unless include
  names them"), corrected in the same initiative; placeframe's datamodels uses
  `force-include` for the same file — inspect and drop it the same way.

### The devkit chain (sweep order)

1. **release-devkit** (`dev`) — handled by `release-devkit-finish.md` (executes BEFORE this
   sweep): lint trim to found-file model, zizmor adoption, self-lint at own pin, static
   self-pin pair-bump + `--head-sha` flip, dry-run self-test, prose fixes. That doc's final
   SHA is T_FINISH, this sweep's pin target. Sweep remainder rides work-plan Step 2
   (ci-devkit): re-base its `ci-devkit` floor to `>=0.3.0.dev{count}` (old run-id-keyed floor
   is dead either way) and relock.
2. **bashrun** (`dev`) — Gen 3→4: pin bump, `prerelease`→`release --channel dev`, merge-gate
   flag, config `registries:`→`registry:`/`identity:` + drop `ci_workflow:`, add
   `update-pr-draft-release`; **bump 0.5→0.6** (retires the never-stable, poisoned 0.5 line).
   After green + merge, publishes `0.6.0.dev{count}` — the floor everyone else relocks onto.
3. **ci-devkit** (`dev`) — same Gen 3→4 set + **bump 0.2→0.3** + floor bashrun + relock. Keep
   the `tools/devkit` sidecar lock discipline (python-devkit exact-pinned in
   `tools/devkit/uv.lock`, checked with `uv lock --check --project tools/devkit`). Publishes
   `0.3.0.dev{count}`; re-base release-devkit's floor in the same step. The merged `f18ae7d
   wip` commit is understood and benign: it IS ci-devkit's Gen-2→3 migration (pin
   1130b98→029a9a6, `publish-prerelease`→`prerelease` rename, `pull_build`→`pull_artifact`
   API rename + AGENTS.md sync) — safe to stack on.
4. **python-devkit** (`dev`==`main`, checkout `main`) — Gen 2→4: rename `publish-prerelease` job
   to `prerelease`, all verb/config/anchor migrations + **bump 0.2→0.3** + floors (bashrun,
   ci-devkit) + relock.
5. **docker-devkit** (`dev`) — already Gen 4: **bump 0.2→0.3** (skips past the uninstallable
   0.2.0 stable and the poisoned 0.2.1 line) + floors + relock, keep green. Verify
   `validate-release-plan` passes (it's the reference).
6. **unity-devkit** (`dev`) — already Gen 4: **bump 0.2→0.3** (PyPI package AND playerbuild
   npm entry) + floors + relock, keep green (self-consuming Unity compile-check legs on
   self-hosted runners).
7. **logger-conf**, **openapi-clientgen**, **pydantic-settings-pulumi** (`dev`) — Gen 2→4 set +
   **bump 0.2→0.3** each + floors + relock. These have `0.2.x` remote branches and
   `origin/update-release-devkit` — stale, ignore.

### The app/consumer tier

8. **placeframe** (`dev`) — biggest consumer. Work: pin→`84afa7a`; verbs (`prerelease`→`--channel
   dev`, merge-gate flag); **add missing `update-pr-draft-release`** (absent today — lint will
   demand it); config migration: 8× `registries:`→`registry:`/`identity:`, drop `ci_workflow:`;
   **add `built_images: true`** (confirmed: repo-local `build-docker` calls docker-devkit
   `run_build(mode="ci")`, which shelves the `images-digests/all` manifest at the PR head);
   **sweep: +1 minor on all 8 package entries** (see bump table) + floors onto docker-devkit/
   unity-devkit/python-devkit/logger-conf/openapi-client-codegen new lines + relock; same-repo
   UPM sibling pins stay `0.0.0+local` sentinels (publish patches them).
   `placeframe/.github/workflows/AGENTS.md` documents the OLD contract (ensure-release-pr /
   publish-prerelease era) — prose update needed in the same change (doc is load-bearing for
   agents). `cesium.yml` is a dispatch-only Cesium native-package builder — likely untouched by
   this migration; post-trim the found-file lint signature-checks EVERY workflow file, cesium.yml
   included — confirm its checkouts/steps conform (or fix them in the same change). Local branch `more-ci-fixes` (5 commits: pin→`ed406a0`, R3/nuget
   package-decl fixes, prerelease draft permissions) is in-flight prior work — fold it in or
   supersede it. placeframe's preflight needs `mirror-images` before it (postgres wrapper FROM
   mirror-pinned base) — preserve the root ordering.
9. **placeframe-capture-tool** (`dev`) — pin bump, verbs, config (old app `builds` dict-with-
   registry-and-artifacts → list form; drop `ci_workflow:`), add `update-pr-draft-release`
   (absent), floors onto devkit new lines + relock, adopt new-line UPM pins for cross-repo
   packages it consumes (placeframe's npm packages, playerbuild — verify the consumed set).
   Local `update-release-devkit` branch (pin `28c8cd2`) is ahead-ish but stale vs the plan
   here — supersede.
10. **Make-it-Sing** (on `ci-support-redux`) — landing strategy first: `dev` branch is still
    Gen-1 (ci.yml); ci-support-redux holds the Gen-3.5 CI. Plan: bring ci-support-redux up to
    Gen 4, get green, merge to `dev` via its own merge-gate once live, then treat `dev` as
    evergreen. Work: pin `28c8cd2`→`84afa7a`; `prerelease`/`release`→`--channel` forms;
    `update-pr-draft-release --pr-number … --run-number …`→`release --channel pr` (old verb
    fails lint); merge-gate flag; config: drop `ci_workflow:`, app `builds` dict→list; **add
    `built_images: true`** (confirmed: `build-livekit-token` runs `uv run build --mode ci`);
    replace the exact `docker-devkit==0.2.1.dev37485576216` pin with a `>=` floor on the new
    0.3 line (policy decided — no `==` anywhere); floors on bashrun/python-devkit/unity-devkit
    new lines; adopt new-line UPM pins (placeframe/lbe-toolkit/playerbuild — verify consumed
    set); relock. `build-livekit-token` / `build-docker` jobs are repo-local — fine.
    `mirror-images` root precedes `preflight`.
11. **lbe-toolkit** (checkout `main`, Gen-1) — build on `ci-support-redux` (Gen 3 @ `029a9a6`):
    bump pin, verbs, merge-gate flag, **add missing `update-pr-draft-release`**, config
    `registries:`→`registry:`/`identity:`, **sweep: 1.0→1.1 on all three package entries**
    (first real publish of livekit/photon — their `0.0.0-local` history is left behind), delete
    legacy `publish-config.json`, floor unity-devkit new line + relock. npm identities
    confirmed `org.outernet.lbetoolkit[.livekit|.photon]` (as authored on the branch) —
    trusted-publisher rows for those three names must be bound to `release.yml` (operator
    task, see Open questions). Then land to `dev`, retire old ci.yml/release.yml.
12. **infra trio** (`infra-github-org`, `infra-github-runners`, `infra-rathole`, all `dev`) —
    non-publishing: integrate.yml + merge-gate.yml only. Pin bump, merge-gate `--head-sha` flag,
    add `&setup-release-devkit`/`&uv-restore` anchors to canonical shape. **Decision:
    canonicalize preflight** — replace the hand-rolled `uv sync; ruff; basedpyright` battery
    with `uv run preflight-python`, which adds python-devkit as a dev-group dependency + lock
    to repos that currently have none, and therefore must follow step 3 (python-devkit's new
    line) for the relock. infra-github-org also owns the `evergreen-dev` ruleset + merge-bot
    App config — new-paradigm repos may need ruleset/secret wiring there (MERGE_BOT_APP_ID
    vars, MERGE_BOT_APP_PRIVATE_KEY secrets, UNITY_* secrets per repo).

## Work plan (the DAG sweep — one package line at a time, root → tip)

Hard ordering constraints: release-devkit pin SHA must exist on remote before consumer CI runs
(satisfied — T_FINISH is pushed by definition of the finish doc landing); a package's new-line
prerelease must exist on PyPI/npm before downstream relocks reference it; each repo lands on
its own `dev` via its own merge-gate (label `ready-to-merge`) once integrate is green. One
repo = one PR carrying its CI migration (where not yet Gen 4) + its `major_minor` bump + its
floors onto upstream new lines + relock.
The sweep's bump table (published packages; app entries in release-devkit.yaml are untouched —
app versions are not registry-consumed, so no poison and no consumer pins; flag if you want
apps bumped too):

| Package | major_minor now → new | First new-line publish lands |
|---|---|---|
| bashrun | 0.5 → 0.6 | step 1 |
| ci-devkit | 0.2 → 0.3 | step 2 |
| python-devkit | 0.2 → 0.3 | step 3 |
| docker-devkit | 0.2 → 0.3 | step 4 |
| unity-devkit + playerbuild (npm) | 0.2 → 0.3 | step 4 |
| logger-conf | 0.2 → 0.3 | step 4 |
| openapi-client-codegen | 0.2 → 0.3 | step 4 |
| pydantic-settings-pulumi | 0.2 → 0.3 | step 4 |
| placeframe's 8 packages | +1 minor each (api-client 0.1→0.2; core/arfoundation/magicleap 1.0→1.1; auth/logging/common/core-python 0.1→0.2) | step 5 |
| lbe-toolkit's 3 packages | 1.0 → 1.1 | step 5 |

- **Step 0 — release-devkit**: confirm `release-devkit-finish.md` has landed — both PRs in,
   dev CI green at the recorded T_FINISH (source of truth; no major_minor — it is never
   published). Every later step pins T_FINISH.
- **Step 1 — bashrun** (leaf). CI Gen 3→4 + config schema + bump 0.5→0.6 → land → publishes
  `0.6.0.dev{count}`.
- **Step 2 — ci-devkit.** CI Gen 3→4 + bump 0.2→0.3 + floor `bashrun>=0.6.0.dev{count}` +
  relock (keep the `tools/devkit` sidecar lock checked) → land → `0.3.0.dev{count}`. Same
  step: re-base release-devkit's floor to `ci-devkit>=0.3.0.dev{count}` (the old run-id-keyed
  floor is dead either way) + relock release-devkit.
- **Step 3 — python-devkit** (checkout `main`; dev==main). Gen 2→4 + bump 0.2→0.3 + floors
  (bashrun, ci-devkit new lines) + relock → land → prerelease. This step also lands the
  preflight deptry fix (branch `deptry-src`: `deptry .` → `deptry src` — a repo-root scan
  resolves absolute self-imports to the project's editable install and deptry misclassifies
  them as transitive, DEP003); release-devkit (already carrying absolute imports and no
  `known_first_party`) relocks its dev group onto the new line — that
  relock closes its deptry red window, the branch's landing gate.
- **Step 4 — docker-devkit, unity-devkit, logger-conf, openapi-clientgen,
  pydantic-settings-pulumi** (parallelizable once steps 1–3 published). docker/unity are
  already Gen 4: bump + floors + relock + verify green. The other three carry Gen 2→4
  migrations. Each lands and publishes its `0.3.0.dev{count}` (unity-devkit also republishes
  playerbuild as `0.3.0-dev.{count}` on npm when its path diffs).
- **Step 5 — placeframe, lbe-toolkit.** Full consumer migrations (see per-repo items) +
  bump their own packages' major_minors + floors onto all step 1–4 new lines + relock +
  UPM-internal updates (placeframe's Packages/manifest.json carries `0.0.0+local` sentinels
  for same-repo siblings — no change needed there). placeframe's new-line npm/nuget/PyPI
  prereleases publish on its merge. lbe-toolkit landing additionally needs the operator's
  wiring (see operator-owned prerequisite below) — verify before labeling.
- **Step 6 — placeframe-capture-tool, Make-it-Sing.** Migrations + floors + relock + adopt
  new-line UPM pins for cross-repo packages (placeframe's, lbe-toolkit's, playerbuild) in
  their Unity projects' `Packages/manifest.json` — exact pins, adoption commits (verify the
  actual consumed set during execution). Make-it-Sing lands ci-support-redux→dev here; its
  landing needs the operator's wiring (see operator-owned prerequisite below).
- **Step 7 — infra trio.** CI-shape updates can go any time after step 0; the
  canonicalized `preflight-python` + python-devkit dev-dep + relock must follow step 3.
- **Step 8 — green sweep + promotion.** Every repo's dev CI green; promote `dev`→`main` where
  the new files must reach the default branch (merge-gate green wake is inert until then; new
  publishing repos' trusted-publisher rows also bind at first stable). Stables of the new
  lines (0.6.0, 0.3.0, …) happen naturally via later promotions — the sweep deliberately does
  NOT promote. Update stale agent docs (placeframe `.github/workflows/AGENTS.md`) alongside
  code changes.

Sessions: one step (or one repo of steps 4–6) per session; each repo's change is one PR to its
own `dev`, certified by its own integrate, landed by its own merge-gate.

## Open questions / to verify before or during execution

Resolved this session by direct verification (registry APIs + code reading) and folded into the
sections above: dev-prerelease availability (registry state block), `built_images: true` for
placeframe and Make-it-Sing (both confirmed needed), the ci-devkit `wip` commit (benign
Gen-2→3 migration), pin policy (`>=` floors, never `==`), un-poisoning strategy (major_minor
bump), the bashrun 0.5 jump (moot — sweeps to 0.6), the broken-stables question (no yank), the
infra trio preflight (canonicalize onto `preflight-python`), and the release-devkit self-pin
(static pin like every consumer; atomic pin+invocation pair bumps with self-test guards — see
Decisions and devkit chain step 1). Open items: none.

Operator-owned prerequisite (not agent work): before Make-it-Sing and lbe-toolkit PRs can land
(steps 5–6), the operator completes on their own timeline — `evergreen-dev` ruleset membership
for both repos (infra-github-org), `MERGE_BOT_APP_ID` var + `MERGE_BOT_APP_PRIVATE_KEY` secret
per repo, `UNITY_*` secrets for their compile-check legs, and npm trusted-publisher rows for
the three `org.outernet.lbetoolkit*` packages bound to `release.yml`. The agent does NOT
prepare the ruleset PR; verify wiring exists (or ask) before labeling those repos' PRs.

Standing constraints (not questions): the GitHub App token cannot push or merge (Contents: write
not granted; see AGENTS-SHARED.md) — lands needing push go through each repo's own merge-gate bot
or the operator; and never label a PR in a repo without a live verification job — lbe-toolkit and
Make-it-Sing must not see `ready-to-merge` before integrate.yml runs on their PRs. Sweep scoping
assumption: app entries in release-devkit.yaml (makeitsing 0.1, capture-tool 1.0) are NOT bumped
— app versions are not registry-consumed; flag if you want them bumped too.

## Ambiguity note (per AGENTS-SHARED.md)

"Most up-to-date branch … where up-to-date only applies to whether the ci files themselves are
up to date" was read as: rank branches by release-devkit pin generation + lint-contract shape
(verbs/anchors/job set), ignoring non-CI divergence. For every repo except lbe-toolkit and
Make-it-Sing the answer is `dev` (or the identical `main` where dev==main); for those two it is
`ci-support-redux`, as tabled above. If "up to date" also meant *closest to
the new paradigm including repo content readiness* (e.g. placeframe's `more-ci-fixes` carrying
partial next-step work), the ranking would fold in those in-flight branches — flagged in the
per-repo sections instead of the table.
