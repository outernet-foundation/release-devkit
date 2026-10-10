# Supply-chain control (parked design record)

Implementation deferred by operator ruling (2026-10-09): all supply-chain questions —
sensing AND restocking — park here as one future comprehensive initiative. The
universal interim answer is manual operator bumping (Interim policy). Nothing here
is built or load-bearing yet. Resume after the devkit rearchitecture's fleet cutover
lands (plan-devkit-rearchitecture.md Phase 7); the sensing half meanwhile stands exactly as
committed (`--offline` in `lint_workflows.py` — the API-dependent zizmor audits
`impostor-commit` and `known-vulnerable-actions` simply never run).

## Scope map: the org's chain, link by link

"Supply chain" here is broader than this note's open questions — most links already
have standing controls, recorded so a resuming session doesn't re-derive them:

| Chain link | Standing control | Open question |
|---|---|---|
| Python dependencies | committed `uv.lock` closure (the seal); `>=` floors + relock via the fleet sweep (plan-devkit-rearchitecture.md Phase 7) | none parked |
| Docker base images | digest pins in `workloads/images.lock`; the org mirror namespace (upstream-yank immunity, docker-devkit AGENTS.md) | none parked |
| npm / nuget adoption | exact pins; adoption is a human commit by law | none parked |
| GitHub Actions references | D1/D2 (appendix): SHA pins centralized — post-rearchitecture third-party SHAs pin inside github-actions-devkit's reusable/composite; consumers carry only local-job wrappers (checkout, setup-uv) | **both halves below — this note** |

## The taxonomy this file turns on

Two categories were mashed under "linting" and must stay split:

- **Static analysis (SAST/lint):** a pure function of the files. Same input, same
  output, forever. Pinning *shape*, template-injection, dangerous-triggers — and
  zizmor's `--offline` persona is exactly the switch that reduces zizmor to this.
- **Supply-chain scanning (SCA):** a function of (our references + the world's
  current knowledge). Same input, different output next week because an advisory
  published or upstream tagged a release. The time-variance is the feature: these
  are sensors on the outside world, not judges of our text. Dependabot alerts,
  `known-vulnerable-actions`, `impostor-commit` (an integrity check — "does this
  reference point at canonical upstream state" — same category operationally: a
  query against external state).

## The sensing problem (the zizmor online question)

D1 (hash-pin everything) fills the fleet with raw 40-hex SHAs. A SHA in a file
proves nothing about itself: a typo'd SHA that still exists (wrong commit, fork
commit, planted commit) is indistinguishable from a real release commit at any
distance. The only verification is a query to GitHub ("does this SHA hang off a
tagged release of that repo?") — word for word the `impostor-commit` audit, which
the offline persona skips. The one check that guards the SHA-pinning decision is
the one switched off.

Yield facts (verified): GitHub advisory coverage for Actions is thin — few actions
ever get GHSA entries, so `known-vulnerable-actions` has low real-world yield.
`impostor-commit` is the workhorse, and Dependabot does NOT cover it (Dependabot
resolves tags; it will not flag a typo'd-but-existing SHA).

## The restocking problem (pin-bump maintenance, the audit's P5 — appendix D9)

Post-D2 every repo carried four wrapper SHAs (`checkout`, `setup-uv`, `mint-token`,
`nuget-login`) that never move until someone moves them — the flip side of
hash-pinning: upstream fixes, the `client-id` spelling unblock, and future action
majors all arrive as "someone must bump the SHA," per repo, forever. The
rearchitecture shrinks the per-repo inventory (mint-token and nuget-login move
inside github-actions-devkit's reusable/composite; consumers keep checkout/setup-uv
for local jobs) and concentrates the fleet's pins in the devkit repo itself — now
the largest single pin owner. Pre-D1 tag
pins floated silently; post-D1 staleness is total without an actuator. This half
is ordinary dependency maintenance (no adversary needed) but is parked WITH the
sensing half because the decision spaces are welded: the natural tools bundle
both halves (Dependabot = advisory sensor + version actuator in one proprietary
GitHub service; Renovate the FOSS-runnable alternative in the same shape), so
choosing an actuator alone pre-shapes the sensor and topology choices. The
devkit-owned alternative is actuator-only: a bump verb/scheduled job that walks
wrapper SHAs against upstream latest-release SHAs and opens PRs through the
normal merge-gate — same central-scheduled topology as the sensor lane below.

## The operator principle (decided 2026-10-09, binding for the future design)

A check gates on what it certifies. Static checks certify "this change is
well-formed" — failures are always caused by the change, so they gate the PR.
Non-static checks certify "our references are sane given today's world" — failures
may have no causal change, so they must never gate a PR:

- **Never fail integration.** An advisory published overnight reddens every open
  PR in the org simultaneously, all demanding one single fix — zero information
  per blocked PR. API calls in the hot path also import flakiness unrelated to
  code.
- **Merge to dev: moot** once integration holds — merge-gate's all-green assert
  reads required checks; no non-static check is ever required.
- **Publishing is where a hard guarantee belongs** — the artifact does not embed
  the Actions pins, the pipeline runs them; what a publish gate protects is
  pipeline integrity (the build system as attack surface). Asymmetry to design
  around: a compromised pipeline is dangerous from its FIRST dev publish (dev
  prereleases feed downstream repos within a day), not only at stable promotion.

## The sensing lane design (agreed shape, unbuilt)

| Lane | What runs | Blocks | Answers |
|---|---|---|---|
| PR gate (integrate) | zizmor `--offline`, as today | yes | is the change well-formed |
| Scheduled sensor | zizmor online, periodic | nothing — alerts | has the world changed under our pins |
| Stable pre-flight | zizmor online, first step of the stable channel | stable publishing only | does anything ship through a toolchain we know is compromised |

Mechanics: zizmor runs twice — the offline invocation stays inside
`lint-workflows` untouched; the online invocation is a separate step elsewhere
with a token (ambient `github.token`, `contents: read`, suffices). The sensor
gives responsiveness (advisory drift and fat-fingered SHAs caught within a poll
period); the stable pre-flight gives the hard guarantee. Neither alone covers
both exposures; the intended endpoint is both, sensor first (no gate semantics
to design, no hostage risk).

Scoped reversal, recorded so it is not re-litigated: the audit (appendix fact 2) rejected
`--no-exit-codes` for the LINT gate (correct — a gate must fail); in the sensor
lane it is precisely correct (a sensor must not fail its job, it must speak).

## Open sub-decisions (the resume agenda)

1. Topology: where periodic org-wide jobs live — sensor home, bump machinery,
   and the lander alternatives (D10's rejected branches, appendix) share one "central
   scheduled job vs per-repo cron vs external service" question; decide once,
   together.
2. Stable pre-flight blocking policy: any finding vs high-only (hostage-release
   trade at promotion time).
3. Actuator: Dependabot vs Renovate vs devkit-owned verb — decided with (1) and
   the sensor, per the welding argument above. Interim: `zizmor --fix=safe` can
   perform initial D2 hash-pinning mechanically (appendix fact 11); it is
   a rollout aid, not maintenance.

## Interim policy (binding until this note resumes)

- **All pins bump by operator act, manually, across the board.** Wrappers
  centralize SHAs so a bump is one file per repo per action.
- The interim decays silently into "never": staleness has no alarm. Known items
  currently gated on a bump: the `client-id` mint-step spelling flip (actionlint
  metadata), future `actions/checkout` / `setup-uv` majors, D3's `$/` flip
  (devkit-internal: the `ACTIONLINT_VERSION` pin rides github-actions-devkit's own dev
  flow, not consumer machinery).
- Sensing gap accepted: SHA pins enter the fleet with no automated real-release
  verification (impostor risk). Mitigations: pins are few, centralized, and
  human-copied from upstream release pages at re-pin time.

## Resume trigger

The zizmor audit's static components implemented and the rearchitecture's fleet cutover
complete (plan-devkit-rearchitecture.md Phase 7) — then this file joins
the agenda as its own initiative, decided together with the lander topology question
wherever it resumes; bump machinery may ride the fleet-sweep machinery.

## Appendix: zizmor audit record (2026-10-09)

Decisions D1–D10 below are binding; the live gated items (D3 `$/` flip, D4 actionlint
keep, D5 no-merge-queues) are carried in `plan-devkit-rearchitecture.md`; this appendix is the
evidence base and decision rationale for this note and for the `$/` flip when its gates pass.
The audit's session narrative and executed-item records live in git log, not here. Post-audit
SHA citations in older records may be pre-rebase spellings of content now on `lint-trim` as
`ada7279`/`624d806`.

### Context

`lint-workflows` runs three layers: actionlint (pinned 1.7.12, checksum-verified download),
zizmor (exact pin 1.30.1, `--offline --format plain --no-progress`, config committed at
`src/release_devkit/verbs/zizmor.yaml` beside the runner, applied via `--config` so consumers
never carry one), and the pure-Python found-file lint. The config's sole surviving relaxation
is `self-repository: disable`, load-bearing until the `$/` flip.

CAUTION: checking zizmor's exit code through a pipe (`zizmor ... | tail; echo $?`) reports the
exit of `tail`, not zizmor — this produced one wrong conclusion during the audit (fact 1).
Use `${PIPESTATUS[0]}` or no pipe.

### Verified facts (do not re-derive)

1. **Exit status: nonzero on ANY finding.** One low-severity self-repository finding → exit 12;
   with high-severity findings present → 14; clean → 0. An earlier session claim that low/help
   findings are "advisory-only, exit 0" was a pipe artifact and WRONG. The runner
   turns any nonzero exit into lint failure, so a rule whose findings are merely low-severity
   still needs `disable` (or `--min-severity`, fact 2) to stay green.
2. **CLI knobs:** `--min-severity <level>` filters findings below the level entirely (not
   printed, no exit effect); `--no-exit-codes` makes findings not affect exit (rejected for the
   gate — hides real failures); personas `regular`/`auditor`/`pedantic`.
3. **Config knobs:** `ignore` supports `filename.yml[:line[:column]]` — line scoping exists but
   is brittle across consumer line drift. `disable` is documented by zizmor as last resort
   (disabled rules vanish from ignored/suppressed counts).
4. **What each relaxation actually suppresses** (raw findings, no config):
   - `unpinned-uses` (high): every `uses:` in the fleet — checkout@v5, setup-uv@v7,
     create-github-app-token@v3, NuGet/login@v1. Blanket hash-pin default since zizmor 1.20.
   - `self-repository` (low): one finding per local wrapper `uses:`. Audit introduced in
     zizmor 1.30.0.
   - `dangerous-triggers` (medium): merge-gate.yml's `workflow_run`.
   - `github-app` (high): the mint step — "app token inherits blanket installation permissions".
   - `template-injection`: merge-gate.yml:38 `--head-sha` interpolation (high) in all repos;
     unity integrate.yml:89 matrix (medium) and :92 needs-outputs (info).
5. `unpinned-uses` supports `config.policies` (per repository-pattern: `hash-pin` | `ref-pin` |
   `any`; implicit `"*": hash-pin`). A bare unpinned `uses:` does not even parse in zizmor 1.30
   (model error); branch pins satisfy `ref-pin`; `"*": ref-pin` greens the fleet.
6. **github-app conformance verified end to end:** flat inputs `permission-contents: write` +
   `permission-pull-requests: read` on the mint step silence the audit. The action supports
   them natively, and actionlint 1.7.12 accepts them (input validation confirmed active via
   bogus-input control). The `permissions:` map input does NOT silence zizmor 1.30 — only the
   flat spelling works.
7. **template-injection conformance:** env indirection (`env: X: ${{ ... }}` + `$X` in run)
   silences the audit — verified; it is zizmor's documented remediation.
8. **`$/` self-repository syntax** (GA 2026-07-30): `uses: $/...` resolves to the workflow's
   own repository at the exact running commit, no checkout required, works in steps/composite/
   nested/reusable calls; requires runner ≥ 2.336.0; GitHub treats it as pinning (SHA-pin
   policies become enforceable for self-references). Fork caveat: resolves the merge ref (fork
   content) — not a fork hardening. zizmor 1.30.1 parses `$/` fine. **No released actionlint
   accepts it** (1.7.12 rejects "ref is missing"). The runner fleet is self-hosted
   (infra-github-runners): verify its version before any flip.
9. **actionlint live-value inventory** (all probed): expression/matrix/needs reference errors
   (unique value concentrated on paths that never execute pre-landing: release.yml, merge-gate's
   wake); runner-label typos (only validator — GitHub silently queues forever; custom labels
   declared via `.github/actionlint.yaml`, unity-devkit carries one); input-typo validation for
   only 2 of the org's 4 actions (checkout and create-github-app-token yes; setup-uv and
   NuGet/login absent from the bundled dataset — `enable-cach:` typos sail through); shellcheck
   integration INERT (no shellcheck binary in the environment — obvious shell bugs pass clean);
   the untrusted-inputs check is the ONLY injection coverage inside the two zizmor-ignored
   files (integrate.yml, merge-gate.yml).
10. The offline persona skips API-dependent audits (impostor-commit, known-vulnerable-actions)
    — the "N suppressed" counts in every run.
11. No repo in the org runs Dependabot (only vendored node_modules copies). `zizmor --fix=safe`
    can perform initial hash-pinning mechanically.
12. **Platform fact:** in-Actions event-driven green-detection is `workflow_run` or nothing —
    `check_run`/`check_suite` never fire for Actions-created checks, and no `pull_request`
    activity type fires at checks-green. Any design avoiding workflow run replaces the wake
    with a poll.
13. The zizmor runner's input must be the repo root, not `.github/workflows` only — wrapper
    action files under `.github/actions` escape the audit otherwise (verified: wrapper-internal
    unpinned uses flagged only when the input is widened). actionlint DOES follow local actions
    transitively.
14. **Empirical template-injection taint map (zizmor 1.30.1, expression probes):** fires HIGH —
    `github.event` free-text fields (PR title), `github.ref_name`, `github.actor`, and the
    ENTIRE `github.event.workflow_run.*` context (coarser than `pull_request`:
    `workflow_run.head_sha` is tainted by context while `github.event.pull_request.head.sha`
    alone is recognized immutable). Fires MEDIUM — `matrix.*` only when the matrix is
    dynamically composed (`fromJson(needs.…)`); statically written matrices do not fire. Fires
    INFO — `needs.*.outputs.*`. No finding: `github.event.pull_request.head.sha` alone,
    `github.event.pull_request.number`, `github.sha`, `github.repository`. Shell quoting of the
    interpolation changes nothing. Env indirection is clean — env values are data by
    construction: bash parses the literal script into commands before parameter expansion, so
    tainted text can arrive only as word content, never as operators.
15. **The unity integrate matrix finding was substantively correct, not a false positive:**
    `projects.py` validates `unity-devkit.json` `name` as non-empty only (no charset law), and
    the matrix derives from the PR head tree, so a PR author controls `matrix.project-name`
    text verbatim. D7's env indirection makes the vector inert; source-side charset validation
    is therefore unnecessary for injection safety.
16. **checkout v7 pwn-request defaults (GA 2026-06-18):** `actions/checkout` v7 refuses
    fork-PR-head checkouts in `pull_request_target` and `workflow_run` workflows by default
    (the latter only when `workflow_run.event` is a `pull_request*`) — fork `repository:`,
    `refs/pull/N/{head,merge}` refs, and head/merge-SHA refs, with opt-out via the deliberately
    alarmed `allow-unsafe-pr-checkout`. Bites when pin bumps cross v7: fork-shaped wakes fail
    the checkout itself (the platform's grain is hardening against the workflow_run shape).
17. **The fact-12 wall is workflow-trigger-scoped.** GitHub App webhooks receive
    `check_suite`/`check_run` completed events for Actions-created checks (the documented
    CI-server pattern; the bors-ng/Kodiak/Mergify lineage) — an external event-driven lander is
    possible without polling. tide (pure poll, 1m sync) and Zuul (webhooks + speculative
    gating) anchor the central-service tier. Parked with D10's rejected branches.
18. **GitHub merge queue supports merge/rebase/squash methods** (queue-controlled; the 2023-era
    merge/squash-only limitation is gone) — recorded against any D5 revisit. The queue still
    cannot express head-identity certification: it lands merge-group trees, never the
    byte-for-byte certified PR head.
19. **zizmor's repo-root scan respects .gitignore** (verified on Make-it-Sing: the gitignored
    Unity `Library/PackageCache` tree — vendored livekit packages carrying their own
    `.github/workflows` — is not collected). The widened runner input is safe on Unity repos:
    CI checkouts carry committed files only, and locally the ignore keeps generated trees out
    of the audit.

### Operator decisions (2026-10-09, binding)

D1. **Hash-pin everything, third party included.** Supersedes the recorded "no SHA-pinning /
    out of scope" positions. The `unpinned-uses: disable` stanza died with the implementation.
D2. **Pins centralize in per-repo composite wrappers**, one per third-party action
    (`.github/actions/{checkout,setup-uv,mint-token,nuget-login}/action.yml`): SHAs live only
    inside wrappers; call sites use local refs (eventually `$/`). Obligations: inputs/outputs
    explicitly forwarded (composites have no passthrough); the checkout wrapper defaults
    `persist-credentials: false`; the zizmor runner input widens to the repo root (fact 13);
    **consumer file change + devkit re-pin must be atomic per repo** — the flip rides the fleet
    sweep (plan-devkit-rearchitecture.md Phase 7), not a file-only PR. Post-rearchitecture
    note: mint-token and nuget-login move inside github-actions-devkit's reusable/composite;
    consumers keep checkout/setup-uv wrappers for local jobs only.
D3. **`$/` adoption: yes, when both gates pass:** an actionlint release supporting `$/`, and
    the runner fleet verified ≥ 2.336.0. The flip changes call sites + lint constants + tests
    and deletes the self-repository disable in the same change. Interim: keep `./` and the
    disable — it is load-bearing (fact 1). Considered, not adopted: runner flag
    `--min-severity medium` fleet-wide — a fleet policy choice to revisit deliberately, not
    slip in.
D4. **actionlint: keep.** Its live value is fact 9's list; reassess only if upstream stalls on
    `$/` support for months. Replacement stack if ever ditched (strictly worse): in-lock
    schema validation (e.g. check-jsonschema against GitHub's workflow schema) and living
    without expression typing.
D5. **No GitHub merge queues — permanent.** Standing principle: keep the system as decoupled
    from GitHub Actions as possible. Grounded by fact 18 (queue lands merge-group trees, never
    the certified PR head).
D6. **github-app: conform.** Flat `permission-contents: write` + `permission-pull-requests:
    read` inputs on the mint step (fact 6's verified spelling — the only form that silences
    zizmor 1.30 and passes actionlint 1.7.12). The two scopes cover the merge bot's whole
    footprint (landing push / branch delete / draft delete = contents: write; gh pr view/list
    = pull-requests: read); the evergreen-dev ruleset bypass is identity-level and unaffected
    by scoping.
D7. **Grammar law amended: tainted-source expressions consumed by `run:` ride the step env
    block.** New law: ambient facts stay ambient (no interpolation anywhere);
    attacker-controllable expressions a `run:` step consumes ride the step env block with the
    run line referencing the variable (the flag stays the verb API, env is the transport);
    known-immutable contexts (fact 14's no-fire list: `github.event.pull_request.head.sha`
    alone, `.number`, `github.sha`, `github.repository`) may interpolate directly. The
    parse-order guarantee is the mechanism (fact 14). Under the rearchitecture the law applies
    inside every devkit-owned workflow file; application sites in consumer files shrink to
    local preflight jobs.
D8. **Supply-chain scanning parked as its own future initiative.** The non-static question
    (offline persona vs online) is deferred whole to this note; the offline persona stands as
    committed; the skipped audits stay skipped; the interim risk is accepted and recorded
    here.
D9. **Pin-bump maintenance parked into the same note** — one comprehensive supply-chain
    initiative decides sensing and restocking together (tooling welds them: Dependabot bundles
    advisory sensor + version actuator). Interim policy (binding): all pins bump by operator
    act, manually.
D10. **Keep the per-repo lander; label-only wake.** The sole wake is
    `pull_request: [labeled]` on `ready-to-merge`; the label means "attempt the merge now" —
    landing = remove-and-re-add the label once green AND rebased. Soundness rests on two
    verified properties: the all-green battery excludes the merge-gate check by name
    (`GATE_CHECK_NAME`), so failed early pokes cannot poison re-pokes; and the wake carries no
    authority — every precondition (label, OPEN, checkout-is-head, all-green, rebased-onto-dev)
    is re-derived at execution. The wake's failure mode is a loud refusal, never a silent
    stall. Residuals unchanged: vacuous green on repos without live verification (hence the
    standing never-label law), the mint step (D6-scoped), the two-poke merge race (second push
    loses loudly). Rejected branches, with reasons, so they are not re-litigated: GitHub merge
    queue (cannot express head-identity certification — fact 18; moves landing policy into
    forge config; still Actions-resident — contra D5 twice over); external lander daemon (new
    always-on host; the App PEM wants a home disjoint from runner code-execution boxes — new
    infrastructure); central scheduled lander (fleet-wide singleton stall risk; the 60-day
    scheduled-workflow auto-disable on quiet repos; the org's first runtime cross-repo
    coupling); per-repo cron (the same auto-disable footgun × fleet size, ~4.3k polling
    runs/day); label-waiter and integrate-tail variants (more machinery buying UX this decision
    deliberately declines). The design space is two families (a forge event wakes privileged
    code vs a lander that goes and looks); label-only is the cleanest member of the first
    family and the only one that is per-repo, Family A, and free of new footguns.

### Live follow-up

- D3 `$/` flip: watch actionlint releases; verify the runner fleet version; flip spelling and
  delete the self-repository stanza in one change. Gating and (much reduced) scope carried in
  `plan-devkit-rearchitecture.md` (out of scope section).
