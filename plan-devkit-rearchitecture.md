# Devkit rearchitecture — binding-layer consolidation, package split, fleet cutover

Status: consolidates and supersedes `release-devkit-finish.md`, `ci-refresh-seed.md` (folded
into Phase 7), `zizmor-audit.md` (live gated items folded here; residue in
`todo/supply-chain-control.md`'s appendix), and `plan-reusable-workflow-migration.md`
(subsumed). Decisions below are binding for execution sessions. Cadence: one session per PR
where practical, each landing on `dev` via the repo's own merge-gate; each session sized to
the context-window smart zone (operator ruling) — exploration, edits, and verification all
fit without degradation, and when in doubt, split; commit discipline per AGENTS-SHARED (prose
and code in separate commits, no trailers).

## Execution state

Phase 1 has landed: build-artifact-registry is renamed, merged to dev, and published
(`0.1.0.dev38075330641` on PyPI). Phase 0 (the self-pin repair, pinning `792302a290808c588eda84f73b29071e8fc53546`)
is committed but deliberately unlanded — the operator punted landing, and Phase 2 work is stacked on
the same branch (landing deferred until it must happen; the eventual PR carries Phase 0 + Phase 2
together, certified once).

Phase 2 is code-complete on the branch (unpushed): all seven reusables, the release composite,
own `integrate.yml` cut to a `$/` self-call and `merge-gate.yml` the pull_request+workflow_call
hybrid (a workflow cannot `uses:` itself), `scripts/preflight.py` (the harness runs
`uv run scripts/preflight.py`) carrying the self-test inline, the lint gut to the disposition table's four checks, `ci_step` killed,
runner provisioning absorbed (`setup.py` since dissolved into its consumers — second-session
paragraph below; `third-party/` stays vendored), the relock onto build-artifact-registry, the
AGENTS.md rewrite, and merge keys forbidden outright (the whole-step anchors that once
compressed the trio died with the `$/` composites). Execution decisions folded in:
the registry floor is spelled `>=0.1.0.dev0` (the plan's `>=0.1` cannot resolve a `.dev` prerelease
under PEP 440, and a run-id floor would die on the first count-keyed publish); actionlint 1.7.12
lacks `job.workflow_*` support and no release carries the fix (rhysd/actionlint#696, #707), so the
lint bridges with `-ignore` flags (four now — the two `job.workflow_*` flags went dormant when
those contexts moved inside `toolkit-checkout`, two more cover the `$/` spelling per
rhysd/actionlint#732; all retire when the ACTIONLINT_VERSION pin moves past the fixes); the
release composite
self-install off `github.action_path` (the archive download is the install); the docker
`build --push` explicit-parameter contract is defined binding-side as step env
`REGISTRY`/`REGISTRY_USERNAME`/`REGISTRY_TOKEN` (docker-devkit 0.3 implements to it, per Phase 4);
the unity leg schema contract is `project`, `platform`, `editor-image` (the license cache key is a
run-wide getter output via `unity-license-tag`, not a leg key — run-fact partition in Execution
state). Still open from
"To verify": PyPI/npm/nuget trusted publishing through composite-wrapped steps (bashrun pilot,
Phase 6); the branch's own certification runs red on preflight-python's deptry step (`deptry .` at
repo root, the known python-devkit bug — either land Phase 5's fixed line and relock first, or accept
the red window). Next: Phase 3 (unity-devkit).

The setup composite (built as the "bootstrap composite fixup", renamed before landing) was
code-complete on the branch until the composite recut below dissolved it: `.github/actions/setup`
once owned the install trio, all ten call sites cut to `uses: ./.github/actions/setup`, and the two
actionlint `-ignore` bridge flags retired early as predicted — every `job.workflow_*` spelling now
lives inside the composite, which actionlint does not parse (1.7.12 remains the newest release, so
the flags cannot retire by pin bump). Execution decisions folded in: the composite references
`job.workflow_*`/`runner.temp` directly — the unverified-context fallback was not needed (the `job`
context hydrates at job initialization per actions/runner#4335 and the Sept 2026 `job.workflow_*`
rollout, so composite steps evaluate inside the same job; the only self-hosted executions, the unity
legs, pass `toolkit: false` and never evaluate it; a guard step fails loudly on empty
`job.workflow_*` before checkout could misresolve to the consumer repo); composite inputs are
untyped strings because no released actionlint accepts the `type:` key on action inputs, so
boolean-ish inputs compare against `'true'`; build-docker's leg threads `free_disk_space` into the
`toolkit` input and the free-disk-space verb now runs after the trio (verified safe — it removes apt
packages, docker images, and swap, nothing uv's install touches); merge-gate's head-first order
normalized to toolkit-first. Also fixed in passing: the release composite's NuGet login step carried
`if: inputs.nuget == true` — untyped composite inputs are strings, so string `"true"` never equals
boolean true and the step would never have run; now `== 'true'`. The anchors died with the trio's
repetition — no workflow file carries any; the sanction stands in AGENTS.md. The release composite
subsequently split per channel into `release-dev`/`release-stable` (operator ruling: a static
per-channel `uses:` beats a runtime channel guard in bash; the `nuget` input survives on both).
The split itself was later superseded: typed inputs dissolved its reason (see the `$/` flip
paragraph — one `release` composite, typed `stable` boolean, no bash guard anywhere).

The composite recut is code-complete on the branch (operator rulings, 2026-10-10, same session as
the matrix refactor): the setup composite is dead and every reusable spells its install trio
inline — toolkit self-checkout with raw `job.workflow_*` (no emptiness guard: hosted runners are
current, the unity legs never run binding verbs), consumer checkout with raw
`fetch-depth`/`fetch-tags` spelled per site (plain is checkout's defaults, by omission), setup-uv
(preflight the only saver). Anchors are whole-step only, on byte-identical repeated steps
(`&toolkit-checkout`, `&consumer-checkout`, `&setup-uv` — operator ruling, 2026-10-10: an anchor
on the pin scalar shares one string and buys nothing, so action pins are spelled raw at every
site), and build-docker's twin toolkit checkouts anchor whole. The build-docker leg takes its toolkit checkout
unconditionally now — the typed `free_disk_space` boolean gates only the verb step, killing the
free_disk_space→toolkit coupling. The release composites carry zero inputs: NuGet routing switched
to the presence of the `NUGET_USER` repo secret, mapped once by the consumer in workflow-level
env, with the login gated on `env.NUGET_USER != ''` inside the composites. Two platform facts
forced that shape (both now in the verified-mechanics section): the `secrets` context is withheld
from composite actions entirely — the branch's original `secrets.NUGET_USER` spelling was a parse
failure the VSCode language server caught before any run — and local `uses:` inside a composite
resolves against the consumer's workspace, so the researched sibling-prelude extraction is
impossible until the `$/` flip; the release pair stays self-contained, the duplicated prelude the
accepted price. Consequence: `job.workflow_*` spellings are back in workflow files, so the two
actionlint `-ignore` bridge flags are restored in `lint-workflows` verbatim. The composite
layering law is recorded in AGENTS.md (composites are leaves: values through inputs, structure
through references, no runtime spelling checks); the one residual conditional is the NuGet login's
env-presence gate — `env` in a composite `if:` is listed available but historically buggy, so the
placeframe pilot leg verifies it live.

The matrix/version refactor is code-complete on the branch (unpushed), riding the same PR as
Phase 0 + Phase 2: `matrix-envelope` is renamed `matrix` and subsumes per-leg version enrichment
(owning-app resolution via `apps.{name}.builds[].project`, the bare `version` base stamped into
owned legs), and `get-app-version` is dead —
console script, tests, and AGENTS.md commands row absorbed into the `matrix` row.
`build-unity.yml`'s `app-name` input and the getter's version step are gone; the legs read
`matrix.version`. A project built by two
apps fails loudly at the getter; legs without a `project` key and unowned projects pass untouched.
The compile-check getter keeps its plain-depth clone — its stamps are inert by design, so the
tagless derivation is harmless. End-to-end exercise still waits for Phase 3 (unity-devkit emits
`project-name` until then).

The run-fact partition refactor is code-complete on the branch (same stack, 2026-10-10 session):
matrix legs now carry only per-leg-varying facts, and every getter output has exactly one
producing step. The `matrix` verb stamps the bare `{next_version}` base and emits exactly one
thing — the envelope; the getter derives the license cache key by calling the domain verb
`unity-license-tag` (daily UTC tag, grammar stays domain-owned) and `commit-count` with a plain
`git rev-list --count HEAD` count step; the fanout threads base and ordinal to the build verb as
separate facts (`--version`, `--commit-count`) — no YAML composes anything, and the verb renders
the pair (`bundleVersion = {version}+{commit-count}`, `AndroidBundleVersionCode = commit-count`)
from one input, so the string and the integer cannot disagree. The leg's step env groups every
fact by source — the leg's matrix facts (project, platform, version), the event fact
(pr-number), the run-wide getter outputs (commit-count, license cache key), the unity secrets,
the registry trio last — and the run line's switches follow that same order with the secrets
elided (`--project`, `--platform`, `--version`, `--pr-number`, `--commit-count`,
`--license-cache-key`, `--registry`); the registry auth env drops the `CI_` prefix
(`REGISTRY_TOKEN`/`REGISTRY_USERNAME`, matching the docker explicit-parameter contract — the
reader is build-artifact-registry's `registry_auth` neutral chain, whose rename is a small API
bump sequenced with Phase 3). The getters renamed to their role (`get-unity-matrix` →
`plan-unity-builds`, `get-compile-check-matrix` → `plan-unity-compile-checks`,
`get-docker-matrix` → `plan-docker-builds`, the last for pattern-consistency). Rationale: a matrix
include entry carrying a run-wide constant lies about cardinality, a verb named for the envelope
must not leak side outputs (the count's only legitimate role was the `+{count}` version
suffix — composing that belongs to the build verb, which receives base and ordinal as separate
facts and renders both Unity fields), and unity-devkit
printing `license=` `$GITHUB_OUTPUT` lines was platform
knowledge leaking into the domain — Phase 3 now also deletes that line, completing the domain
verbs' de-flavoring to a bare JSON array. The output key, env var, and domain flag spell
`license-cache-key`/`LICENSE_CACHE_KEY`/`--license-cache-key` (operator ruling, same session: the
value is the ORAS tag the license cache restores under, not a license — the old `--license`
invited reading it as a credential or file). Accepted trade: fanout env values are mixed-sourced
(`matrix.*` for leg facts, `needs.*.outputs.*` for run facts) in one canonically-ordered block —
cardinality truth over the single-data-bus uniformity.

Two same-day hygiene rulings (2026-10-10): `banner()` — the ci_step-replacement separator —
is deleted outright, no replacement (the separator log bought nothing; the "plain banners"
language below means plain prints, never a helper), and `tags.py` folded into `plan.py`
(compute_release_plan already did its git I/O through it), with the one write,
`create_and_push_tag`, living in `verbs/release.py` beside its only callers. A follow-up
ruling: `--locked` is universal — every `uv run` in devkit-owned files carries it (domain
verbs, consumer scripts, binding verbs alike), so a consumer lock out of date with its
pyproject fails loudly at the first leg instead of uv re-resolving on the runner; the
`--no-sync` on the preflight-python run died with it.

Same session, ruled out (do not re-propose without new information): an added composite-lint
layer (bettermarks/composite-action-lint surveyed) was declined.
Platform facts learned: `$/` shipped on github.com 2026-07-30 (runner ≥ 2.336.0; the
changelog names composite steps and nested composition), actionlint support is open PR
rhysd/actionlint#732 — 1.7.12 still rejects the spelling — and `./` local-action refs
resolve against the consumer's workspace from called reusables too, so the dissolved setup
composite would have failed its first remote run: the recut dodged a platform wall, not
just a taste problem. Also ruled: the consumer-head checkout ref stays binding-internal —
`github.event.pull_request.head.sha || github.sha` is the certification invariant (build the
tree that will land, not github.sha's merge preview), single-copied; as a consumer input a
wrong spelling would shelve artifacts under a SHA release never pulls and fail late.

The `$/` flip landed on the branch (operator ruling, same session, superseding the
composite-dedup ruling above — carrying the actionlint bridge is the new information): the
install trio is three composite actions (`toolkit-checkout`, `consumer-checkout`,
`setup-uv`) referenced via `$/` from every reusable, and `integrate.yml`'s own preflight
call flipped with them (zizmor's self-repository audit endorses the spelling for workflow
refs too; its stanza died with the last `./`). The composites are leaves carrying values
only (`ref`/`fetch-depth`/`fetch-tags` on consumer-checkout, `save-cache` on setup-uv,
nothing on toolkit-checkout); every whole-step anchor died with the trio's inline
repetition; the lint carries two new `-ignore` bridge flags for rhysd/actionlint#732 — one
for the action-rule error, one for the workflow-call rule — each anchored on the `$/`
spelling so `./`-ref and remote-format errors stay live, retiring when the ACTIONLINT_VERSION
pin moves past the fix (the two job.workflow_* flags went dormant the same day: those
contexts moved inside toolkit-checkout, where actionlint never looks). Actionlint blindness
into the composites is accepted (zizmor still audits them, third-party pins included).
Carried risks, ruled acceptable without a pilot: `$/`-from-a-reusable-workflow semantics
(self must resolve to the file's repo at the called SHA, not the caller's repo — the exact
bug class `./` has) and the unity self-hosted fleet's runner version (needs ≥ 2.336.0; the
unity legs execute consumer-checkout and setup-uv on that pool). First live exercise
surfaces both. Same ruling, follow-on: the trio composites' inputs are typed (`type: number`/
`type: boolean`, unquoted defaults) — the untyped-string constraint was an actionlint artifact,
void the moment actionlint stopped parsing these files. Same follow-on, second: the release
pair merged back into one `release` composite on the typed `stable` boolean (the split's
bash-guard comparison is moot when the platform types the input; the two files differed in
exactly two values — `persist-credentials`, forwarded raw from the input, and the channel
string, rendered from it via step env `RELEASE_CHANNEL`); fleet-free because no consumer has
cut over yet. setup-uv stays inline in the release composite rather than referencing the
`$/setup-uv` sibling — composite-inside-composite `$/` is the least-exercised corner of the
2.336.0 rollout, not worth a third unpiloted behavior for a four-line dedup.

Every question from drafting is resolved and folded into the sections below.

Second session (2026-10-10, later), all on the same branch and the same eventual PR, in order:
the delivery-surface check inside `validate-release-plan` was deleted outright (the "wip"
commit was ruled intentional — the verb is the bare plan core; its doc row and tests went
with it); `setup.py` dissolved to zero — `configure_git`/`install_dotnet`/`install_node`
live in `verbs/release.py` beside their sole callers (`install_dotnet` takes `settings`
as a parameter because config's `Settings` validates runner env at run time, never at
import), the free-disk logic lives in its verb file with a module-local Windows settings
read, and `github_path` joined `config.Settings`; then the `$/` flip, typed composite
inputs, and the release-pair merge per the paragraph above the ruled-out list. The branch's
own certification remains red only on preflight-python's deptry step (the known
python-devkit bug — either land Phase 5's fixed line and relock first, or accept the
window). Next: Phase 3 (unity-devkit), per the section below.

Landing prerequisites (operator-owned, recorded here so no session re-derives them): the branch is
local-only and must be pushed before any CI runs; this repo's own merge-gate hybrid reads the App
key from a secret spelled `merge-bot-private-key` (kebab — no forwarding hop, unlike consumers'
`MERGE_BOT_APP_PRIVATE_KEY`) plus the `MERGE_BOT_APP_ID` var, so both must exist in this repo under
those names before the first `ready-to-merge` label.

### Matrix/version refactor (before Phase 3)

Executed on the branch, riding the Phase 0 + Phase 2 PR: per-leg base-version stamping; `get-app-version` died as a verb. The
single `app-name` input on `build-unity.yml` names ONE app while the matrix spans projects — in a
multi-app repo every leg stamps the one named app's version (wrong `major_minor` base, wrong patch
line for the others). Latent today (capture-tool, the sole consumer, is single-app) but the design
bakes in the wrong model. Binding decisions folded in (operator session 2026-10-10):

- `matrix-envelope` renames to `matrix` and subsumes version enrichment: for each leg, resolve the
  owning app via the config (`apps.{name}.builds[].project` against the leg's `project` key) and
  inject `version` (the bare `{next_version}` from that app's `major_minor` + `{app}-v*` tags)
  into the leg — the only per-leg stamp, since versions vary by owning app. `commit-count` (the
  repo-wide `git rev-list --count HEAD`, shared by the Android bundleVersionCode law) never
  enters the verb: the getter's count step derives it, and the fanout threads base and ordinal to
  the build verb as separate facts (`--version`, `--commit-count`), the verb composing
  `bundleVersion = {version}+{commit-count}` and stamping `AndroidBundleVersionCode` from the one
  pair (run-wide facts
  never ride matrix legs — cardinality law; run-fact
  partition in Execution state). The pipe reads `build-unity-matrix | matrix` — domain emits
  candidates, the binding's matrix composes the final fanout.
- Zero inputs: `app-name` dies entirely, the getter's version step dies, the `version` job output
  dies (version rides the leg). The getter becomes one pipe plus two single-output steps
  (license-cache-key via `uv run unity-license-tag` composed into `$GITHUB_OUTPUT`; commit-count
  via a plain `git rev-list --count HEAD` — the daily-tag
  grammar stays domain-owned); the "second stamper" workflow_call.outputs question dies with it.
- Seam law: version derivation stays binding-owned — the enrichment calls the same library math
  (`next_version`, tags) the release verb uses; unity-devkit stays version-blind. The `+{count}`
  build suffix is the build verb's rendering: it derives neither fact, it composes both Unity
  fields from the threaded base-and-ordinal pair.
- Pass-through rules: legs without a `project` key pass untouched (docker: `targets`/`variant`); a
  build leg whose project no app owns builds unversioned (already a supported mode); compile-check
  legs get versions injected inertly (they don't stamp). The empty-legs loud guard stays.
- `get-app-version`'s console script, AGENTS.md commands row, and its tests absorb into the new
  verb; AGENTS.md's installation/matrix paragraphs and the "No verb takes a SHA flag" tail update
  with it.
- Caveat: enrichment keys on the contract spelling `project` — unity-devkit emits `project-name`
  until Phase 3, so end-to-end exercise waits for Phase 3; the binding already anticipates the
  post-Phase-3 spellings. The rename is free now (only this repo's three getters call the helper)
  and expensive after Phase 7 — it rides in the same change.

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
- **The platform binding** — release-devkit renamed **github-actions-toolkit** (plural, matching
  the product): everything that knows GitHub Actions exists. One repo, clone-pinned,
  dependency-of-nothing. Holds: all reusable workflows, the release composite, `lint-workflows`,
  the merge-gate bot, the release/delivery verbs (OIDC trusted publishing, Releases API,
  `GITHUB_REF` parsing are platform-bound), runner provisioning (absorbed `setup.py` +
  vendored `third-party/`), and the matrix helper. Its own `uv.lock` resolves
  `bashrun` + `build-artifact-registry` + pydantic/strictyaml/typer.
- **build-artifact-registry** — ci-devkit's surviving half, renamed to its job: registry
  primitives for pushing/pulling build artifacts, locally or remotely (`builds`, `cache`,
  `setup_oras`, `registry_auth`). Purely registry concerns; no presentation, no runner
  knowledge. ghcr is a registry choice passed as a parameter, not platform coupling.

Supporting laws:

- **Verbs are named for side effects, never execution context.** "ci" is a context; shelf/push
  is a side effect. `ci-build-unity` → `build-unity` with no mode switch (operator ruling,
  2026-10-10: shelving is implied by supplied registry env — the flag was judged noise in the
  verb's CI shape; docker keeps its explicit `--push`); docker's `build --mode ci` →
  `build --push` (image push + digest manifest), with runner provisioning peeled to binding
  pre-steps.
- **Stable-CLI-API doctrine is fleet law**: script names and flags are public API for every
  devkit, not just the binding repo — structure (in github-actions-toolkit) and code (in
  consumer locks) are pinned by different mechanisms, so the YAML's expected verb surface must
  not move silently.
- **Prose rule**: fleet docs retire bare "registry" — "package registry" for the publishing
  side (PyPI/npm/NuGet), "build-artifact registry" for the OCI artifact side. Existing adapter
  names (`NuGetRegistry` etc.) already follow the cargo-qualified pattern; only prose changes.
- **Fleet YAML formatting is retained, not reformed**: blank lines between jobs and top-level
  keys, permissions and secrets as block maps. The migration changes structure, not style.
- **No GitHub merge queues**, permanently: they land merge-group trees, never the certified
  PR head. actionlint stays; reassess only if upstream stalls on `$/`.

## Binding decisions (operator, 2026-10-09 session)

- All reusable workflows (preflight, mirror, update-pr-draft-release, merge-gate, unity
  build/compile-check, docker build) live in github-actions-toolkit. release-devkit is
  renamed github-actions-toolkit. Pinning stays lint-enforced multi-spelling (literal `@<full-
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
  at exactly the pin the caller spelled. This is github-actions-toolkit's install mechanism
  inside its reusables.
- **`uses:` is resolved statically by GitHub, server-side.** No expressions, no env, no
  filesystem. Cross-repo refs must be `owner/repo/.github/workflows/file.yml@ref`; `./` refs
  resolve same-repo at the caller's commit — github-actions-toolkit's own `integrate.yml` calls
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
- **The `secrets` context never enters composite-land** (verified 2026-10-10). Withheld from
  action files entirely — a parse failure (`Unrecognized named-value: 'secrets'`), not an empty
  string (github/docs#12705; the VSCode language server enforces the same availability list) —
  and unavailable in `if:` conditions even in workflows. Crossing points: workflow/step `env:`
  and step `with:`, in workflow context only. Consequence: the consumer's release.yml maps
  `NUGET_USER` in workflow-level env; the composite gates the login on `env.NUGET_USER != ''`.
- **Local `uses:` inside a composite resolves against the consumer's workspace**, not the
  action's own checkout (actions/runner#1348) — composite→sibling references are impossible;
  the native fix is the `$/` self-repository reference (the tracked, gated flip). Consequence:
  no shared release prelude; the release pair stays self-contained.

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
  cover them (the same reliance the current wrapper law makes). Resolved at the composite
  cutover and superseded by the `$/` flip: actionlint 1.7.12 (still the newest release)
  rejects the `type:` key on action inputs, but it never parses the trio composites (it
  cannot resolve `$/`), so their inputs are typed (`fetch-depth: number`, `fetch-tags` and
  `save-cache: boolean`); the local-action `with:` checking is moot since the recut — no
  local action call sites actionlint can resolve remain in this repo's workflows, so the
  accepted hole is composite internals and remote-action `with:` alike.
- `env` context in a composite step's `if:` (the NuGet login's presence gate): listed available
  in the composite context set, but historically buggy on old runners — first live exercise on
  the placeframe pilot leg (Phase 6).

## Phase 0 — land github-actions-toolkit

The executed trim work sits on `github-actions-toolkit` (renamed from `lint-trim`), unlanded,
carrying its self-pin repair: the rebase after the audit sessions had orphaned the wrapper pin
(an ancestor of neither HEAD nor origin), so the repair re-pins to the newest on-remote
ancestor that carries the current workflow spelling — the branch's origin tip at repair time.
A commit cannot contain its own SHA, so the pin rides a standalone commit; the pinned SHA must
exist on the remote before CI runs, so the branch is pushed before the merge-gate landing. The
trim's own scope is otherwise complete and verified.

## Phase 1 — build-artifact-registry (the ci-devkit split)

- One repo, renamed: ci-devkit → build-artifact-registry (operator-owned GitHub
  rename; the redirect covers old URLs), package and distribution renaming with it.
  `builds.py`, `cache.py`, `setup_oras.py`, `registry_auth.py` stay — this is their repo;
  `install_oras`'s hardcoded `ensure_registry_login("ghcr.io")` becomes a parameter.
  Media-type strings rename to the new writer name safely (restore/pull don't filter on
  them; older manifests still pull).
- `ci_step.py` and `setup.py` (+ `third-party/dotnet-install.sh`) are deleted from the floor;
  setup's destination is github-actions-toolkit's src (Phase 2), ci_step's destination is
  nowhere (banners replace it).
- Fresh `0.1` version line — a new distribution name needs no continuity with ci-devkit's
  line, and a fresh base dodges the poisoned ci-devkit `0.2.1` base; publish dev prerelease;
  the old ci-devkit distribution is frozen forever, **no yank** (broken stables precedent:
  uninstallable pins sink; resolvers move past).
- Operator prerequisite before first publish: the PyPI pending-publisher row binding
  `build-artifact-registry` to this repo's `release.yml` — a new distribution name
  has no publisher until registered.
- Its own repo CI keeps the hand-written shape at current pins until the Phase 7 sweep; keep
  the `tools/devkit` sidecar-lock discipline for python-devkit consumption.
- API breaks ship with the manually bumped `major_minor` per that repo's own release flow.
- AGENTS.md rewritten to the registry-primitives charter (ORAS lives only here; builds ≠
  caches; no runner knowledge — now true with no asterisks).

## Phase 2 — github-actions-toolkit (rename + all binding surface)

- **Repo rename** release-devkit → github-actions-toolkit (operator-owned; GitHub redirects
  old URLs, including `uses:` refs — the lint must enforce the canonical new spelling so the
  redirect can never mask a missed rename). Update clone URLs, `DEVKIT_REPOSITORY`, the
  self-test clone, AGENTS.md title/identity. The dependency-of-nothing law survives the
  rename unchanged.
- **Reusables**, each self-checking-out via `job.workflow_repository`/`job.workflow_sha`,
  third-party action SHAs pinned once here:
  - `preflight.yml` — ONE job, three sequential steps in fail-fast order:
    `lint-workflows` → `validate-release-plan` → the consumer's preflight script; checkout
    PR-head ref law + full fetch internal; one shared runner environment, no internal `needs`
    graph. Sequential steps is the maximal fail-fast: a red PR dies at its first failing step
    before any build leg spends a minute, and a green PR pays three short steps on one runner
    — the serialized premium over a parallel max() is one lint wall-clock on the common path,
    accepted. Placement is economics, not security: a lint job runs inside the workflow it
    lints, so PR-authored YAML can simply delete it — lint-in-integrate is fleet-law
    certification for trusted authors, never a security boundary (workflow-threat-model pass:
    OWASP CICD-SEC-4, MITRE T1677 PPE, GhostAction/tj-actions/Shai-Hulud postmortems).
    Script contract: a required Python script at the repo-root path `scripts/preflight.py`,
    invoked by the harness as `uv run scripts/preflight.py` (a plain uv run — no shebang, no
    executable bit), missing file a loud red — never a skip;
    the harness provides checkout at the PR head, uv, docker on the runner, and cwd = the
    repo root; exit code is the whole interface. Per-consumer variance (e.g. `packages:
    read` for mirror pulls) rides the calling job's permissions, as ever consumer-owned.
    Pure certification: no outputs — the app-version math rides the plan core, so a bad
    `major_minor` line still fails before any build; the version stamp is computed inside
    `build-unity.yml`, its sole consumer.
  - `update-pr-draft-release.yml` — `release --channel pr`; `if: github.event.pull_request`
    internal; `packages: read` at call site; needs the consumer's terminal build legs.
  - `merge-gate.yml` — full-clone checkout of the PR head, internal mint of the merge-bot App
    token (`vars.MERGE_BOT_APP_ID` reads the caller's var; key arrives as named secret
    `merge-bot-private-key`), `merge-gate --head-sha`.
  - `build-unity.yml` / `compile-check-unity.yml` — matrix getter (piping the domain verb's
    bare leg list through the matrix verb, plus the `unity-license-tag` license-cache-key and
    `git rev-list --count HEAD` commit-count steps) + fanout
    internally: `runs-on: [self-hosted,
    unity]`, `container: ${{ matrix.editor-image }}`, wipe-workspace, checkout + setup-uv
    restore, license `--license-cache-key` threading, unity secrets named, registry auth ambient,
    runner-provisioning pre-steps (absorbed `setup`), per-leg base-version stamping via the matrix
    verb (the matrix/version refactor above; the legs read `matrix.version`, the fanout threads
    the getter's run-wide outputs — license-cache-key, commit-count — alongside in the canonical
    order).
    Verb code resolves
    from the consumer's `uv.lock` — the `@sha` pins structure, the lock pins code.
  - `mirror.yml` — the single first root: every other integrate job depends on it
    (transitively). Provisioning precedes consumption, and the long-term destiny is
    `ensure-hermeticity` — images today, packages and actions later (see
    `todo/supply-chain-control.md`) — which is why it comes first now. Mirror login +
    `uv run mirror`.
  - `build-docker.yml` — docker matrix getter + fanout; matrix values env-indirected in
    `run:` lines; `free_disk_space` a reusable input.
- **Release composite** `.github/actions/release` (typed input `stable`, boolean): one
  composite, both channels — superseding the earlier per-channel split (the split beat a
  runtime channel guard in bash; the typed boolean needs no guard, the wrong value is
  unspellable, and the only per-channel differences are values: `persist-credentials`
  forwarded raw from the input, the channel rendered from it via step env). It absorbs the
  checkout/no-ref/tag-fetch law (credentials persist for the tag push only on stable),
  setup-uv, nuget login (`NUGET_API_KEY` minted internally),
  and the verb invocation; self-installs per the to-verify mechanics above. Consumer
  release.yml collapses to triggers + concurrency + delivery jobs of one `uses:` each.
  Delivery jobs stay inline run-step jobs (composite = inline; reusable = forbidden).
- **Matrix envelope helper verb** — stdin leg list → `{"include": …}` envelope →
  `$GITHUB_OUTPUT`, with the empty-legs loud guard.
- **Lint gut** per the disposition table below; delete the integrate/merge-gate grammar, the
  verb spec tables, ref/tag-fetch/verb-installation/env-reference/wrapper validation, the
  one-saver-cache rule, the nuget-key env law (`declares_nuget()` dies with it — content
  validation already lives in pydantic config load and `validate-release-plan`), and the
  `environment:` ban. Add the SHA law; the surviving residue is the disposition table's.
- Own `integrate.yml`/`merge-gate.yml` cut over to `./` calls (no self-pin). The self-test
  survives: dynamic clone at PR head, `validate-release-plan` + `merge-gate --dry-run` with
  cwd = this checkout.
- Kill `ci_step` imports in own verbs → plain banners; absorb `setup.py` + `third-party/`.
- Relock onto `build-artifact-registry>=0.1` (+ bashrun 0.6 line when published).
- AGENTS.md rewritten spec-first in the same PR set (identity, installation section, commands'
  lint row, config's `build_reference` provenance — the sections the consolidation audit
  enumerated).

## Phase 3 — unity-devkit (domain purification + renames)

- `ci-build-unity` → `build-unity`, taking no mode switch: shelving (the build-output push plus
  the license/UPM/library CI cache bundle) is implied by supplied registry env; absent registry
  env is the local build (operator ruling — `--shelf` was noise, implied by the verb's CI
  shape); matrix verbs emit bare leg lists (the leg schema —
  `project`, `platform`, `editor-image` — becomes named contract in its AGENTS.md;
  renaming a key breaks the binding's fanout YAML). The `matrix=`/`license=`
  `$GITHUB_OUTPUT` lines die with the bare-list protocol: the binding's getter derives the
  license cache key by calling `unity-license-tag` directly (daily UTC tag, domain grammar), so the
  domain matrix verbs carry zero GitHub output flavor. The consuming flag renames with it:
  `--license` → `--license-cache-key` on `build-unity`/`compile-check-unity` (the value is the
  ORAS tag the license cache restores under, not a license) — one more API break riding the
  `major_minor` bump.
- `--version-code` → `--commit-count`, and the build verb takes over the stamp composition: given
  `--version` (bare base) and `--commit-count` (ordinal), it stamps
  `bundleVersion = {version}+{commit-count}` and `AndroidBundleVersionCode = commit-count` from
  the one input pair — rendering, not deriving (it performs no tag math, computes no count), so
  string and integer cannot disagree; the seam law amends from "stamps verbatim, no composition"
  to "derives neither fact, renders both fields".
- The neutral registry-auth env drops its `CI_` prefix: the verbs read
  `REGISTRY_TOKEN`/`REGISTRY_USERNAME` (matching the binding's docker explicit-parameter
  contract, which always spelled it this way). The reader is build-artifact-registry's
  `registry_auth` chain — that repo takes the matching rename as a small API bump sequenced with
  this phase; unity-devkit's AGENTS.md env contract updates with it.
- Verb option-declaration order in typer mirrors the binding's switch order exactly — project,
  platform, version, pr-number, commit-count, license-cache-key, registry
  (`compile-check-unity`: project, license-cache-key, registry) — so `--help` and the fanout run
  lines read identically top-to-bottom (operator ruling: the order in these workflow files IS
  the order the typer options are declared in).
- Drop `ci_step` and `setup` imports: provisioning (configure_git, disk space, toolchain
  installs) moves to the reusable's pre-steps in github-actions-toolkit; banners replace
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

- **bashrun** after Phase 2: exercises preflight + merge-gate + the release composite; carries
  the PyPI-through-composite verification gate (fallback decision point for release.yml).
- **placeframe-capture-tool** after Phases 3–4: exercises mirror + preflight, unity build
  (per-leg base-version stamping), docker build, update-pr-draft-release.

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

**Bump table (re-derived for the split).** build-artifact-registry `0.1` (new name,
fresh line). bashrun `0.5` → `0.6` (retires the poisoned never-stable 0.5). python-devkit,
docker-devkit, unity-devkit (+ `org.outernet.playerbuild`), logger-conf,
openapi-client-codegen, pydantic-settings-pulumi: `0.2` → `0.3` (unity/docker rows carry the
API breaks). placeframe's 8 packages +1 minor each (api-client 0.1→0.2; core/arfoundation/
magicleap 1.0→1.1; auth/logging/common/core-python 0.1→0.2). lbe-toolkit 1.0 → 1.1 (all three
packages). App entries NOT bumped (not registry-consumed).

**Per-repo cutover (atomic per repo):** rewrite `integrate.yml`/`merge-gate.yml` to the
consumer end-state shapes, rewrite `release.yml` to composite calls (fallback grammar if the
pilot rejected composites), bump every `uses:` SHA to one fresh github-actions-toolkit SHA and
relock onto the bumped floors — all in the same commit; old files + old pins stay mutually
consistent until the switch.

**Sequencing laws.** Prereleases must exist on the registry before downstream relocks reference
them; devkit repos merge and are pushed first (pins must exist on the remote before consumer CI
runs); one repo = one PR landing via its own merge-gate; the sweep deliberately does NOT
promote to stable (promotions happen naturally later; green sweep then promote `dev` → `main`
where receivers live on the default branch); update stale agent docs alongside code (instance:
build-artifact-registry's AGENTS.md names the binding repo by its abandoned intermediate
spelling in the release-flow section).

**Sweep order.** Devkit self-cutovers first (build-artifact-registry,
github-actions-toolkit's own files beyond `./` refs — none needed, python/docker/unity/devkit
repos themselves), then simple publishers (logger-conf, openapi-client-codegen,
pydantic-settings-pulumi, lbe-toolkit), the infra trio (infra-github-org,
infra-github-runners, infra-rathole — preflight + merge-gate only), app repos
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
`evergreen-dev` ruleset + merge-bot App + `UNITY_*` wiring; **inspect infra-github-org's tree before committing there — reconnaissance
found `src/stacks/dev.py` locally modified, so re-verify current state**.

**pyproject hygiene, every repo, every in-tree pyproject.** Delete deptry
`known_first_party` self-declarations (instance: placeframe `build/pyproject.toml`;
`per_rule_ignores` tables stay; red windows close at each repo's relock onto python-devkit's
fixed line — release-devkit is in that window from github-actions-toolkit on). Delete `[tool.uv]
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
`release.yml`; a per-repo `NUGET_USER` secret for every nuget-publishing consumer (placeframe) —
never org-level, org secrets are fleet-visible and would switch the login on everywhere. The
agent verifies wiring exists before labeling; it does not prepare the
ruleset PR.

**Operator-owned org-level hygiene (threat-model load-bearing, independent of any parked
initiative).** Org-wide push ruleset path-restricting `.github/**` on all branches, bypass =
operator (closes the compromised-member workflow-edit path); fork-approval tier "all external
contributors" on every public repo (fork workflow spellings never auto-run; also rations
hosted-runner slop); org default workflow permissions read-only; "Allow GitHub Actions to
create and approve pull requests" OFF.

## Consumer end-state

Simple publisher (e.g. bashrun) — `integrate.yml` is `preflight` (uses; the script is a
two-line Python file calling `uv run --locked preflight-python` through bashrun) +
`update-pr-draft-release` (uses, `needs:
[preflight]`); `merge-gate.yml` is triggers + concurrency + one gated `uses:` call;
`release.yml` is triggers + concurrency + delivery jobs of one composite `uses:` each — plus,
for nuget-publishing consumers only, one workflow-level env line mapping
`NUGET_USER: ${{ secrets.NUGET_USER }}` (the composite's login gate keys on its presence; see
the composite recut in Execution state).

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
  mirror-images:
    permissions:
      contents: read
      packages: write
    uses: outernet-foundation/github-actions-toolkit/.github/workflows/mirror.yml@<sha>

  preflight:
    needs: [mirror-images]
    uses: outernet-foundation/github-actions-toolkit/.github/workflows/preflight.yml@<sha>

  build-unity:
    needs: [preflight]
    permissions:
      contents: read
      packages: write
    uses: outernet-foundation/github-actions-toolkit/.github/workflows/build-unity.yml@<sha>
    secrets:
      unity-email: …
      unity-password: …
      unity-serial: …

  build-docker:
    needs: [preflight]
    permissions:
      contents: read
      packages: write
    uses: outernet-foundation/github-actions-toolkit/.github/workflows/build-docker.yml@<sha>

  update-pr-draft-release:
    needs: [build-unity, build-docker]
    permissions:
      contents: read
      packages: read
    uses: outernet-foundation/github-actions-toolkit/.github/workflows/update-pr-draft-release.yml@<sha>
```

placeframe: same skeleton plus local `build-docker` / `publish-compose` legs (repo-owned
scripts; `build-docker.yml` replaces the getter + wrapper once Phase 4 lands), unity
`compile-check-unity.yml` call, `update-pr-draft-release` needing `publish-compose` + the
unity fanout; its `scripts/preflight.py` carries the DB battery, and the calling job's
`packages: read` supplies the mirrored postgres the battery pulls. What stays local is an
ownership boundary, not a mechanics one: repo-owned scripts (the preflight script itself
included), `publish-compose`.

## lint-workflows disposition

Philosophy carried from the executed trim: found-file model, no presence checks (accepted
hole: renaming a canonical file dodges its contract — self-inflicted, accepted); taste is not
lint; misordering fails loudly at runtime. The single-copy artifacts make most of the old
surface structurally impossible to drift, so the lint shrinks to exactly four things —
actionlint + zizmor + the SHA law + the concurrency model checks:

| Concern | Disposition |
|---|---|
| actionlint + zizmor layers | unchanged; devkit-owned files audited by the devkit's own self-lint; composite internals zizmor-covered at the devkit root, actionlint-blind (composites fail loudly on bad inputs instead) |
| SHA pin law | **the core check**: every `uses:` ref to github-actions-toolkit (workflow or action) is a full 40-hex SHA; all refs to it in one repo carry the same SHA; the canonical repo name is enforced (GitHub's rename redirect must never mask a stale spelling); within-file YAML anchors on the `uses` scalar sanctioned |
| Inline-delivery law | **dropped** — no delivery reusable exists to forbid; violating requires authoring new machinery (a consumer-local reusable or a devkit-grown one), and the failure would surface at delivery time with a confusing OIDC error; cheap insurance judged not worth a check |
| release.yml concurrency | `release-${{ github.ref }}`, no cancel — the delivery mutex: with no group, concurrent dev runs lose sections to the `dev-builds` read-modify-write race; with cancel, a mid-flight publish dies half-done and the cancelled merge's section is permanently lost (per-SHA snapshots are never rewritten) |
| merge-gate wake shape | labeled-only wake, per-PR serializing group — the group closes the real race (two rapid pokes both read OPEN/green/rebased before either merges → double merge); the labeled-only trigger half guards gate availability (dead-gate detection); the workflow_run half is redundant with zizmor's dangerous-triggers audit and rides along free |
| integrate/merge-gate grammar, verb spec tables, ref/tag-fetch laws, verb-installation, env-reference resolution, wrapper validation, one-saver-cache, nuget-key env law + `declares_nuget()`, `environment:` ban | **die** — absorbed by single-copy reusables/composite (cannot drift), already actionlint/zizmor territory, or moot with the wrapper's death |

## Out of scope (recorded, not planned)

- The `$/` flip's consumer half remains parked: consumers' local-job wrappers
  (checkout/setup-uv) flipping to `$/` — the toolkit flipped its own files already (the
  trio composites + the own preflight call, with the actionlint bridge flags standing in
  for rhysd/actionlint#732), and the bridge retires by pin bump once a release accepts the
  spelling; the unity runner fleet's version is the live gate to watch on first exercise.
- Supply-chain initiative — parked at `todo/supply-chain-control.md` (resume after Phase 7
  cutover). Not adopted there: fleet-wide `--min-severity medium`.
- Hotfix release model — parked at `todo/hotfix-release-model.md`.
- Fork-contribution model — parked at `todo/fork-contribution-model.md`.
- Unity license and runner redesign — parked at `todo/unity-license-architecture.md`.
- Path-diff change-detection bug (build inputs outside a package's declared `path` are
  invisible) — parked at `todo/CRITICAL-BUG.md`.
- Any change to release.yml's inline delivery model beyond the composite; any org-level
  workflow mechanism; renaming canonical workflow filenames (npm/nuget publisher bindings
  forbid it).
