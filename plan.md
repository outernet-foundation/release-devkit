# plan.md — the single-verb release arc

Transient working artifact for a three-session refactor arc. **Delete this file in session 3's final commit.** Durable truths belong in AGENTS.md, not here; this file carries order-of-operations, audit findings, and session specs. Status markers live here by design (it is the per-initiative plan file, exempt from the no-status-markers rule that governs state files).

---

## Order of operations

### Session 1 — drafts.py wrangle + this plan (DONE)

`create_or_update_release` was reduced to a linear spine through a series of commits (`01cd150` → `4cdda28`, branch `backup`): identity resolution hoisted, tag composition folded, config loading moved into the function, `context.py` deleted (`build_context` inlined, env guard → `Settings.require_runner_environment`), manifest pull moved to `required=False` + fused with the images table at the bottom, `DigestEntry`/digest constants folded in, `builds.py` deleted, every conceptual block commented. ci-devkit side: `pull_build` → `pull_artifact(required=...)`, `build_exists` deleted (commits `8883550` → `bf9011d`, branch `update-release-devkit`, git-pinned in pyproject at `bf9011df20c481f7ae6ffaed9581cd134f0512f2`).

Investigation conclusions feeding sessions 2–3: the three verb files are byte-identical except the channel literal; trusted publishing binds to workflow *filename* (`release.yml`), not verb name, so the collapse is OIDC-safe; consumers pin by full SHA so nothing breaks until a consumer bumps its wrapper pin.

### Session 2 — lint-workflows rebuild (grammar rides here) (DONE)

Aggressive code-quality pass on `src/release_devkit/verbs/lint_workflows.py` + `tests/test_lint_workflows.py`, **ending with the deliberate grammar flip to the single-verb paradigm** — the lint accepts `release --channel pr|dev|stable` spellings while the three old verbs still exist as scripts. Operator ruling: behavior-preserving-only was rejected; the grammar change rides session 2, session 3 lands the verbs. Constraint that follows: **no consumer pin may be bumped between session 2's push and session 3's push** — an intermediate pin would lint-reject old spellings while the new spelling doesn't run yet.

Landed (commit order): actionlint module extracted (`src/release_devkit/actionlint.py`, tarball deleted, paths quoted); TypeGuard family replaced by a pydantic-validated typed view (`StepView`/`JobView`/`WorkflowView`, parse-boundary shape problems, yaml-1.1 `on:`/True quirk folded into `WorkflowView.triggers`); `Problem` dataclass as the validators' currency with rendering at the two public boundaries; `RepoContext` replacing the drilled `nuget` booleans; `validate_job` decomposed into per-concern checks with one parametrized `canonical_mint_steps` collector and `steps_in_window`; the six verb tables consolidated into `VerbSpec` + `RELEASE_CHANNELS` with `DEVKIT_INVOCATION` derived and a pyproject drift-guard test; duplicate wrapper steps rejected; `signatures_for` computed once per file; the grammar flip (`release --channel pr|dev|stable`, channel-conditional placement/checkout/env/delivery) with fixtures rewritten around `job_block`/`workflow` builders and the channel matrix tests. 86 tests green, ruff + basedpyright clean, repo baseline unchanged (46 test-side pyright errors, 4 collection errors — session 3's batch).

### Session 3 — verb collapse + ci_step helpers + module move (NEXT)

Collapse `release`/`prerelease`/`update-pr-draft-release` into one `release --channel` verb, extract the three draft stages into helpers behind `ci_step`, move drafts.py's contents into the verb file, fix the deferred test-fallout batch against the final module home, final AGENTS.md truth pass, delete plan.md.

---

## Locked decisions

- Single console script `release`; flag `--channel pr|dev|stable` (values are `ReleaseChannel` StrEnum members; typer renders the choice). `--config` unchanged. Script name stays `release`.
- The lint grammar flips in session 2 (before the verbs exist in new form). No consumer bumps between session 2 and session 3 pushes.
- Helpers: exactly three (`publish_packages`, `stage_app_builds`, `render_built_images`), explicit parameters, **no context bundle dataclass** — `VerbContext` was deleted on purpose this arc; three helpers with genuinely different param subsets is where a shared bundle over-carries.
- Each helper wraps itself in `with ci_step(...)` internally (the `preflight.py`/`merge_gate.py` pattern).
- The deferred test-fallout batch (4 pytest collection errors, 46 basedpyright errors — all test-side, from the `context.py`/`builds.py` deletions and API renames) is fixed **in session 3**, once, against the final module home (`release_devkit.verbs.release`), not against the current `release_devkit.drafts` paths.
- plan.md is deleted in session 3's final commit.

---

## Session 2 — lint-workflows audit and proposals

Audit performed against `backup @ 4cdda28`; line numbers are indicative. Test coverage is broad (fixtures cover nearly every rejection), so the refactor has a safety net — keep the test names' semantics alive through the rewrite.

### A. Verb grammar scattered across six synchronized tables (the core defect)

The verb surface is enumerated in `VERB_CHECKOUTS` (62), the `DEVKIT_INVOCATION` regex alternation (83), `VERB_ARGS` (86), `VERB_ENV` (95), `NUGET_DELIVERY_VERBS` (43), plus `[project.scripts]` in pyproject. Adding or changing a verb means editing 5+ sites in agreement; nothing checks they agree — worse, line 557 does `VERB_ARGS[verb]` unguarded, so a verb present in the regex but missing from `VERB_ARGS` **crashes the lint with KeyError instead of reporting a problem**. A latent drift-crash class, not hypothetical hygiene.

**Proposal:** one declarative spec table is the single source of truth:

```python
@dataclass(frozen=True)
class VerbSpec:
    name: str
    args: re.Pattern[str]
    env: dict[str, str]
    checkout: str  # signature key into the checkout-signature table
    delivery: bool  # nuget mint window applies
    channels: Mapping[str, ChannelSpec] | None  # only the release verb
```

`DEVKIT_INVOCATION`'s alternation, the per-verb lookups, and the delivery/reservation checks all derive from it. A consistency guard (or derivation-by-construction) makes table drift structurally impossible. This is also exactly the seam the single-verb flip needs: the `release` entry gains `channels` and everything else generalizes.

### B. Channel dimension for the single-verb grammar (the flip itself)

**Proposal:** `ChannelSpec(args, env, checkout, delivery, workflow, job)` per channel:

- `pr` → `--channel pr`, `GITHUB_TOKEN: github.token`, checkout-with-tags, not delivery, lives in integrate.yml's PR-draft job
- `dev` → `--channel dev`, `GITHUB_TOKEN: github.token`, checkout-with-tags, delivery, lives in release.yml's dev job
- `stable` → `--channel stable`, `GITHUB_TOKEN: github.token`, checkout-with-tags-push, delivery, lives in release.yml's `release` job

`NUGET_DELIVERY_VERBS` dies (delivery becomes channel-derived). The invocation regex captures verb+args; channel parses out of args. Job-placement rules become channel-conditional. Open item for session 2's start: survey the three consumers' job names (placeframe's release.yml names its dev job `prerelease`; confirm the PR-draft job name in integrate.yml across consumers) and decide whether job names stay (`prerelease`/`release` keep minimal consumer churn) or rename — recommendation: keep existing job names, map channel→job in `ChannelSpec`.

### C. `validate_job` is a 90-line monolith (340–428)

Ten responsibilities in one function: environment ban, three step collections, reserved-checkout checks, wrapper-precedes-verb, required-checkouts-before-wrapper, canonical setup-uv, mint window, nuget window. The mint (385–401) and nuget-login (402–427) blocks are near-duplicates — same shape: collect canonical steps, validate id+inputs, require one inside the `earliest_wrapper_index < i < first_verb_index` window (that window arithmetic appears three times).

**Proposal:** decompose into one named check per concern over a small typed job view; unify mint/nuget into one parametrized `canonical_mint_steps(steps, uses, step_id, inputs, path, job_name)` returning `(indexes, problems)`; the window check becomes `steps_in_window(indexes, earliest_wrapper, first_verb)`.

### D. Strings as the error currency, format re-assembled at 20+ sites

Every problem string rebuilds `{path}: job '{job}' step {i}: ...` inline; validators return `tuple[list[str], list[VerbStep]]`.

**Proposal:** a `problem(path, job, index, message)` constructor (or tiny `Problem` dataclass) owning the format; validators accumulate `list[Problem]`; `main` renders. Kills the format drift and most of the signature noise.

### E. The type-guard family is unverifiable (170–179)

`is_mapping` and `is_string_mapping` have **identical bodies** with different `TypeGuard`s — `is_string_mapping` asserts str keys without checking any key (yaml 1.1 makes bare `on` a `True` key, proving keys aren't reliably str). Same sin class as `typing.cast`, which house rules forbid.

**Proposal:** a thin hand-rolled typed view layer instead of pydantic models (we are reading, not validating input — pydantic's machinery buys nothing here): `parse_workflow(path)` returning a record of `(raw_text, Workflow)` where `Workflow.jobs: dict[str, Job]`, `Job.steps: list[Step]`, `Step` exposing `.uses`, `.run`, `.with_block`, `.env` as `str | None` / mapping-or-None. All shape mismatch becomes one early problem at the parse boundary; the guard family dies at every use site; the raw text rides along because the physical-line lint (G) needs it.

### F. The YAML 1.1 `on:`/`True` quirk is inline and cryptic (306–308)

Correct but a cold-reader trap.

**Proposal:** fold into the typed view as `Workflow.triggers` with one comment naming the yaml-1.1 boolean-key behavior.

### G. The raw-text `run:` single-line lint re-implements block-scalar scanning (448–500)

Manual fold detection, indent arithmetic, blank-line rules, the 120-char threshold, devkit-never-folds. Reality-checked: each of the three consumers carries exactly one legitimate `>-` fold (long `ci-build-unity` invocations) — the feature is load-bearing, do not delete it. The two-pass structure (parsed + raw) is inherent: the rule is about *physical* lines, which the parsed value cannot see.

**Proposal:** keep the logic, isolate it as its own clearly-bounded section (or helper module), trim the dead `BLOCK_SCALAR_HEADS` entries nobody can produce (`|1`–`|4` indented indicators — verify against consumers, then trim), and add the one comment explaining why raw text is scanned at all.

### H. Parameter drilling with dead defaults

`nuget: bool = False` threads through four layers; `validate_workflow_file(publishing=True, nuget=False)` defaults are never exercised (main always passes explicit).

**Proposal:** frozen `RepoContext(publishing: bool, nuget: bool)` dataclass — one explicit param instead of two drilled ones, no defaults.

### I. `signatures_for(path)` recomputed per checkout step (609)

Per-step recomputation of a per-file constant; also compares `path.name == RELEASE_WORKFLOW.name`.

**Proposal:** compute once per file, pass down; compare against the constant directly.

### J. actionlint bootstrap lives inside the lint module (633–677)

~45 lines of download/checksum/extract provisioning unrelated to lint logic; leaves the tarball in the cache; unquoted paths in command strings.

**Proposal:** extract to `src/release_devkit/actionlint.py` (ensure + run); the verb imports it. Delete the tarball after extraction; quote paths.

### K. Duplicate wrapper steps pass silently (362–372)

Only the earliest wrapper before the first verb matters; a job with three wrapper steps is clean.

**Proposal:** exactly one wrapper step per verb-carrying job. Grammar decision — add a rejection + test.

### L. Dead/contradictory table entries

`VERB_ENV["validate-release-plan"] = {}` is indistinguishable from absence (`.get(verb, {})`); `release`/`prerelease` present in `VERB_ENV` but `get-app-version` absent — no stated rule for which verbs appear.

**Proposal:** subsumed by A (the spec table makes presence structural) — every verb row carries its env, empty or not.

### M. `main` exit-flow is subtle (139–148)

Problems print, then actionlint may `SystemExit(returncode)` mid-flow, then `if problems: SystemExit(1)`. Two error channels with an interleaved external process.

**Proposal:** collect → render problems → run actionlint → single exit decision at the end. Also document (one comment) that `--workflow` with non-canonical filenames intentionally skips the per-file contract checks.

### N. The constants blob is a grab-bag (18–114)

Interleaved spec tables, path constants, regexes, platform maps with no grouping.

**Proposal:** reorganize during the A/B rewrite: spec tables adjacent to their dataclasses, environment constants grouped, actionlint constants moving to J's module.

### O. Test fixtures (892 lines) are thorough but noisy

Same f-string job assembly repeated in ~70 tests; fixtures hardcode the three-verb spellings everywhere.

**Proposal:** keep the block-string approach and the test names' semantics (they are the grammar's regression spec), add a small `job(...)`/`workflow(...)` builder to cut repetition, rewrite verb fixtures as `RELEASE_PR_RUN`/`RELEASE_DEV_RUN`/`RELEASE_STABLE_RUN` with the `--channel` spelling, and add: the per-channel checkout/env/placement matrix, channel-arg rejections (`--channel bogus`, bare `release`), the duplicate-wrapper rejection (K), and the table-drift guard (A).

### Session 2 execution order (DONE)

1. Survey the consumers' workflows — done; findings below.
2. AGENTS.md prose-first commit — done (`60e5555`).
3. Behavior-preserving code commits — done (actionlint J; typed view E/F; Problem D; RepoContext H; validate_job decomposition C; spec consolidation A/L/K/I/N).
4. Grammar-flip commit with fixtures rewritten — done (`bb6d9a7`).
5. This plan update — done.

**Survey findings (channel→job table, pinned):** the fleet is 12 publishing consumers + the infra trio, not three. All publishing release.yml files name the dev job `prerelease` and the stable job `release` (openapi-client-codegen's `publish-prerelease` job/verb is an ancient-pin outlier that adopts the canonical spellings on bump); the PR-draft job is named `update-pr-draft-release` (Make-it-Sing, the only current carrier). Channel placement as landed: `pr` → integrate.yml's `update-pr-draft-release` job; `dev` → release.yml's `prerelease` job; `stable` → release.yml's `release` job. unity-devkit, docker-devkit, Make-it-Sing, and openapi-client-codegen still carry pre-flag-ban spellings (`--repository/--actor/--workspace/--step-summary/--pr-number/--run-number`, `HEAD_SHA` env) at their pinned SHAs — every one of them already fails the pre-flip lint, confirming they must adopt the lint-blessed spellings at bump time.

**Deviations from the proposals:**

- **Two spec tables, not a `channels` field** (A/B): `VERB_SPECS` (channelless verbs) + `RELEASE_CHANNELS` joined by a `RELEASE_VERB` key. A `channels: ... | None` field on `VerbSpec` would leave the release row's own args/env/checkout/delivery as dead fields (L's sin recreated); the sibling table has no dead data and the same derivation property.
- **The typed view is pydantic-validated, not hand-rolled isinstance** (E): the proposal's "pydantic buys nothing here" was wrong in strict mode — hand-rolled narrowing from `object` propagates pydantic-strict `Unknown`s everywhere (the old TypeGuards were fabricating `dict[object, object]`, the exact sin E flagged). Three `TypeAdapter`s (`dict[object, object]` root — it preserves the yaml-1.1 boolean `True` key so `get("on")`/`get(True)` keep working; `dict[str, object]` inner; `list[object]`) are the sanctioned typed-schema route.
- **`BLOCK_SCALAR_HEADS` became a classifying regex** (G): trimming the dead `|1`–`|4`/`+` entries outright would have let an empty `run: |2` block slip through as an inline value; `^[|>](?:[+-]\d?|\d[+-]?)$` keeps every block head rejected with no enumeration to rot. Fleet scan: only `>`, `>-`, `|`, `|-` ever occur.
- **The drift guard is a pyproject-parsing test** (`test_verb_spec_table_matches_the_console_scripts`) with a `LEGACY_VERB_SCRIPTS = ("prerelease", "update-pr-draft-release")` carve-out for the session-2→3 window. **Session 3 must tighten it to exact equality when the legacy script rows die.**
- **H resolved at the inner layers only**: `RepoContext` replaces the `nuget` drilling through `validate_job`/`collect_verb_steps`/`validate_verb_env`; `validate_workflow_file`'s `publishing`/`nuget` keyword boundary stays — it is the tests' API and its defaults are exercised by them.
- **M folded into D and the flip** (no separate commit): the collect→render→actionlint→exit flow was already the structure; the one comment documenting that `--workflow` under non-canonical filenames skips the per-file contract checks landed in `validate_workflow_file`.
- **AGENTS.md identity paragraph**: the stale `build_context`/`context.py` tail (dead since session 1) was cut in session 2's prose commit rather than left for session 3; session 3 still owns the `drafts.py` → `verbs/release.py` re-spelling.
- **plan.md is itself ruff-formatted** (code blocks) — its comment spacing was normalized by a format run and committed as its own prose commit.

Verification (all green at `bb6d9a7`): `uv run ruff format && uv run ruff check . && uv run pytest tests/test_lint_workflows.py -q && uv run basedpyright` — repo-wide basedpyright stays at the known 46 test-side errors.

---

## Session 3 — spec

### Verb collapse + module move

- Delete `verbs/prerelease.py`, `verbs/update_pr_draft.py`; `verbs/release.py` gains `--channel: Annotated[ReleaseChannel, typer.Option(...)]` and keeps `--config`.
- Move all of `drafts.py` into `verbs/release.py` (constants, `ReleaseChannel`, `DigestEntry`, `create_or_update_release`, helpers, `markdown_table`, `delete_draft_release`); delete `drafts.py`.
- `merge_gate.py:12` import of `delete_draft_release` repoints to `release_devkit.verbs.release`.
- pyproject: three script rows → one `release = "release_devkit.verbs.release:app"`.
- Tighten the lint drift-guard test: drop the `LEGACY_VERB_SCRIPTS` carve-out once the legacy script rows die (see session 2 deviations).

### Helper extraction (inside the moved `create_or_update_release`)

Spine stays: read config/plan → stable stop-guard → identity → scaffolding → channel match → draft ensure → three helpers → section join → splice → notes edit → dev-draft reset. Helpers, each opening `with ci_step(...)` internally:

- `publish_packages(settings, publish_config, release_plan, channel, short_sha, prefix) -> str | None` — provisioning, registries, package loop, Packages table, stable app tagging. `ci_step("Publish packages")`.
- `stage_app_builds(settings, publish_config, channel, sha, short_sha, versions, tag, repository, prefix) -> str | None` — staging loop, asset selection, upload, Apps table. `ci_step("Upload app builds")`.
- `render_built_images(settings, publish_config, sha, prefix) -> str | None` — manifest pull, images table. `ci_step("List built images")`.

Signatures are wide by design (see Locked decisions: no bundle). Callers-before-callees: `create_or_update_release` above the helpers.

### Test-fallout batch (deferred to here, fixed once)

- Imports `release_devkit.drafts` → `release_devkit.verbs.release` (test_draft_releases, test_prerelease, test_release; `DEV_DRAFT_TAG`, `delete_draft_release`).
- `make_context` helpers: drop `publish_config`, `Settings(..., github_workspace=...)` for the env validator.
- `setattr(drafts, "pull_build", ...)` → `setattr(release_module, "pull_artifact", ...)`; repoint `patch_context`/`load_config` seams to the new module.
- `test_merge_identity_falls_back_to_head_on_non_merge` asserts dead behavior — `pytest.raises(IndexError)` or delete.
- `tests/test_builds.py` tests have had no entry point since `build_context` died — rewrite around the new unit seams or delete.

### Closing

- Final AGENTS.md truth pass (module map: drafts.py gone, single verb file; the identity-branch paragraph's `drafts.py`/`context.py` references re-spelled).
- Delete plan.md. Commit. Session 3's push may be followed by consumer bumps (workflow spellings + wrapper SHA atomically per consumer).

---

## Risks

- **Intermediate-pin hazard** (session 2 → 3 window): a consumer bumped to a session-2 pin fails the new lint with old spellings, and the `--channel` spelling doesn't run until session 3. Mitigation: operator bumps nothing in the window; the window is short.
- **Grammar flip without a runnable verb**: session 2's fixtures validate spellings no devkit commit can execute end-to-end yet — CI green is lint-internal only until session 3. Accepted by ruling.
- **Fixture/consumer drift**: the lint tables must match what consumers will actually write; mitigated by the session-2 consumer survey and by consumers copying the lint-blessed spellings on bump.
- **basedpyright 46 / pytest 4 collection errors** remain through the arc (user-owned, deferred by ruling) — the guard is "add no new errors," verified each session.
