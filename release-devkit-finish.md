# Release-Devkit Finish — lint trim, found-file model, self-lint, self-landing

Status: plan complete (2026-10-08); decisions below are binding for execution sessions. This
plan executes BEFORE the consumer sweep (`ci-refresh-seed.md`); that seed retargets its pin to
this doc's final recorded SHA. One session per PR is a reasonable cadence; each PR lands on
`dev` via the repo's own merge-gate (label `ready-to-merge`). Commit discipline per
AGENTS-SHARED: prose and code in separate commits, no trailers.

Addendum (2026-10-09, zizmor audit): PR-2's landing folds the audit's backlog items 1 and 3
(`zizmor-audit.md`) — D1/D2 hash-pinning via per-repo composite wrappers, D6's scoped mint, D7's
env-indirection law, and D10's label-only merge-gate wake all ride this branch's own-file
conformance; the consumer sweep propagates them atomically per repo with the re-pin. The
verification rule "the two reference repos MUST stay green" was the TRIM's rule (it only
loosened); the audit's law intentionally tightens, so pre-sweep consumers DO redden under the
new lint until their sweep step flips their files — by design (D2: consumer file change + devkit
re-pin must be atomic per repo).

## The goal

1. `lint-workflows` shrinks from a repo-schema enforcer to a **found-file form validator**
   (plus two delegated layers: actionlint — already integrated — and zizmor, newly adopted).
2. release-devkit's own workflows become lintable by its own lint at its own pin — no
   self-detection, no repo taxonomy, no special cases.
3. Self-landing modernized: static self-pin pair-bump (`ad42152` → post-trim tip) +
   `--head-sha` invocation flip + dry-run self-test.
4. Stale prose corrected and AGENTS.md synced to the new lint charter.

Consumers at existing pins see zero change throughout; they inherit the trimmed lint when the
sweep re-pins them onto this doc's final SHA.

## Decisions (operator, 2026-10-08)

- **Found-file model.** Scan `.github/workflows/`, lint what is found: filename-keyed full
  contracts for `integrate.yml` / `release.yml` / `merge-gate.yml`; every other workflow file
  gets signature checks only. **No presence checks anywhere** — a missing file means no
  contract applies; presence policy as a concept is deleted, not relocated. Accepted hole: a
  repo renaming a canonical file dodges its deep contract — self-inflicted, not accidental,
  accepted.
- **Declaration consistency** (config declares packages/apps ⇒ delivery surface must exist)
  moves to `validate-release-plan` — a plan-time check in the config-aware verb. Judgment
  call, bounded; delete it too if it grows taxonomy.
- **All style rules deleted** (single-physical-line / fold regime), with **no formatter
  replacement**. Taste is not lint.
- **Tier 1 + Tier 2 both** — the full disposition table below.
- **zizmor adopted**: pinned exact as a release-devkit runtime dependency (PyPI wheels, so the
   clone's `uv.lock` closure stays the seal), invoked by `lint-workflows` after actionlint in
   offline mode, plain format. A small reviewed-exceptions config covers the canonical files'
   known-safe patterns (PR-context `--head-sha` interpolation into `run:`). Tag-pinning policy
   (`@v5` etc.) unchanged — SHA-pinning migration is out of scope. Offline mode skips the
   audits needing `GH_TOKEN`, so the lint job needs no new credentials.
- **Self-landing = static self-pin like every consumer.** The pin and the `merge-gate.yml`
  invocation spelling are one interface, bumped as one atomic commit. Lint-at-own-pin
  supersedes the previously sketched hand-rolled self-test pair check; the dry-run self-test
  stays (different job: verb health, not pair consistency).
- **Sweep retarget**: `ci-refresh-seed.md` pins this doc's final landed SHA everywhere it said
  `84afa7a…`.

## Disposition table (what the trimmed lint does)

| Concern | Disposition |
|---|---|
| Workflow schema, expressions, shellcheck | actionlint (unchanged) |
| Generic Actions security: pinning posture, persist-credentials, template injection, secrets-inherit, insecure-commands | zizmor (new; offline) |
| Verb invocation grammar: known verbs, arg regexes, canonical spelling, env bindings | KEEP (the irreducible API core); add spec↔CLI sync test |
| Wrapper action: one bash step, `RELEASE_DEVKIT_COMMIT` 40-hex, exact clone | KEEP (pin discipline) |
| Found-file contracts: integrate job-graph form, release concurrency/triggers, merge-gate dual-wake `if:`/triggers/concurrency, channel-in-job rules, reserved checkout signatures, `environment:` forbidden, one cache-writing setup-uv per file | KEEP (form of found content) |
| Checkout validation | PROPERTY-IZE: pinned `actions/checkout`; `persist-credentials: false` everywhere except the stable-push signature; per-file ref law (integrate: PR-head ref; release: no ref; merge-gate: dual-payload `\|\|`); tag-consuming verbs' checkouts carry `fetch-depth: 0` + `fetch-tags: true`. Closed four-signature set dies |
| Mention rule | PROPERTY: a run step that EXECUTES a devkit verb must consist solely of canonical invocations. Path mentions alone unflagged (self-test clone passes) |
| `name: "Release"` literal | DELETE; ADD cross-file consistency: merge-gate's `workflow_run.workflows` must equal the found integrate.yml's `name:` (closes the silent-wake-death gap) |
| Dead composite-action `uses:` prefixes | DELETE |
| Step ordering (wrapper/checkouts/setup-uv precede verb; mint window placement) | DELETE — misordering fails loudly at runtime. Keep only: a verb-carrying job contains the wrapper step, and verb env references resolve to real step outputs |
| Single-line/fold style regime | DELETE, no replacement |
| All presence checks (lint root exists; publishing ⇒ jobs exist; publishing ⇒ release.yml; wrapper-not-found) | DELETE. Wrapper/verb coexistence becomes a found-content property (above) |

## Work plan — two PRs (staged self-hosting; each rung certified by the previous rung's output)

### PR-1 — the trim (validated by today's integrate: preflight + dynamic-SHA self-test)

Code:

- Found-file scan replacing `default_workflows()` / `is_publishing()`; delete every presence
  check per the table. Non-canonical workflow files (e.g. placeframe's `cesium.yml`) get the
  signature-check path.
- Mention rule → property conversion per the table.
- Delete `validate_run_steps_single_line` and its constants; delete the dead-uses check;
  delete the `name: "Release"` literal; add the Integrate-name cross-file check.
- Property-ize checkout validation; drop ordering/mint-window machinery, keeping the two
  cheap properties listed in the table.
- zizmor: add the runtime dep (exact pin, relock), invoke after `run_actionlint()`, add the
  exceptions config (committed beside the source; document persona = offline default).
- `validate-release-plan`: add the declaration⇒surface consistency failure.
- `merge-gate --dry-run` mode: full machinery (head→PR resolution, git containment queries,
  API reads), zero side effects; precondition failures are informational (at integrate time
  its own checks are pending and the PR may not be FF from tip) — it certifies machinery, not
  landing preconditions. Note: the existing args regex `^ --head-sha .+$` already admits the
  extra flag (`--head-sha X --dry-run`).
- Self-test extension: integrate's dynamic-SHA self-test additionally runs the PR head's
  `merge-gate --dry-run --head-sha <head>` after `validate-release-plan`. Wrinkle to resolve
  in design: the merge-gate verb spec's env requirement (`GITHUB_TOKEN` from the mint step)
  must gain a dry-run-aware shape — either `github.token` is acceptable for `--dry-run`, or
  the spec keys env on non-dry invocations — don't drag mint machinery into preflight.

Tests:

- Rewrite `tests/test_lint_workflows.py` to the new model: found-file fixtures, property
  checks, style-rule absence, signature-only path for non-canonical filenames, cross-file
  name consistency.
- Add the `VERB_SPECS`/`RELEASE_CHANNELS` ↔ typer CLI sync test if absent (every enforced
  spelling parses against the real verb apps; every real verb/flag is enforced or consciously
  unenforced).

Prose (separate commits):

- Fix the exact-pin falsehood: floors in `pyproject.toml`, the committed `uv.lock` is the
  exact pin.
- Rewrite the AGENTS.md lint-charter sections: found-file model, no style rules, zizmor layer,
  self-lint bootstrap, the deleted presence philosophy.

### PR-2 — self-lint + pair bump (one atomic commit)

- Add a `lint-workflows` job to own `integrate.yml` via the own wrapper; `preflight` `needs`
  it. The wrapper pin in this commit = PR-1's landed SHA.
- Flip `merge-gate.yml`: `HEAD_SHA` env var → `merge-gate --head-sha ${{ … }}` flag; delete
  the env var. Self-pin `ad42152` → PR-1's landed SHA. One commit, both halves.
- Bootstrap consistency: the lint job runs lint-at-PR-1-SHA against PR-2's files — property
  mention rule passes the self-test clone, the flipped spelling passes, an unflipped one
  would fail. From PR-2 on, the pair is machine-checked at every landing.
- Landing: PR-2 is validated and landed by the NEW pair (label wake runs the PR's merge-ref
  file: new pin + new spelling, self-consistent). No chicken-and-egg either way — the old
  `ad42152` pair also still works as a fallback lander.

## Verification

- PR-1: run the new lint against **docker-devkit** and **unity-devkit** checkouts — the
  reference repos MUST stay green (the trim only loosens; if either reddens, the trim
  tightened something). Full test suite green; own integrate green.
- PR-2: own integrate green including the new lint job; land via merge-gate.
- After PR-2 lands, record here: **T_FINISH = `____________`** — the consumer sweep's pin
  target. Update `ci-refresh-seed.md`'s retarget note from placeholder to this SHA.

## To verify during execution

- zizmor exact version at run time; survey its offline findings against the two reference
  repos (expect: reviewed exceptions only, head-sha interpolation chief among them).
- Existing `tests/test_lint_workflows.py` coverage — how much rewrites vs deletes, and
  whether any spec↔CLI sync already exists.
- The nuget config-informed env rules survive property-ization intact (delivery jobs of
  nuget-declaring repos keep the `NUGET_API_KEY` mint binding).
