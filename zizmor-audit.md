# Zizmor relaxation audit — findings, decisions, pending

Status: operator review session 2026-10-09; decisions below are binding, the pending section is
the next session's agenda. This doc is the hydration source for continuing the audit — it carries
every verified fact so the next session does not re-run the investigation. Branch: `lint-trim`
(zizmor adoption commit `5bf7301` is under review here). Continuation session (same date)
resolved P1/P2/P4/P5 as D6–D9; the P3 session (same date) resolved P3 as D10; the item-1 session
(same date) executed backlog items 1 and 3 for this repo's own files (see the final Done section)
— **the next session is the consumer sweep (`ci-refresh-seed.md`), propagating the wrappers, the
scoped mint, D7's env indirection, and the label-only wake atomically per repo with the re-pin;
item 4 (the `$/` flip) stays gated on actionlint support + runner fleet ≥ 2.336.0.**

## Context

`lint-workflows` runs three layers: actionlint (pinned 1.7.12, checksum-verified download),
zizmor (exact pin 1.30.1, `--offline --format plain --no-progress`, config committed at
`src/release_devkit/verbs/zizmor.yaml` beside the runner, applied via `--config` so consumers never
carry one), and the pure-Python found-file lint. The config carries five relaxations; this doc
records the audit verdict on each, the operator decisions, and what remains open.

Audit method: run zizmor raw (no config) vs configured against release-devkit, docker-devkit,
and unity-devkit (the two reference consumers with the full canonical trio + wrapper).

## Reproduction

    # zizmor (exact-pinned in the venv)
    uv run --project /workspace/release-devkit --locked --no-dev zizmor \
        --offline --format plain --no-progress [--config <cfg>] <dir>

    # pinned actionlint binary (rebuilt automatically by ensure_actionlint)
    ~/.cache/release-devkit/actionlint-v1.7.12/actionlint <workflow.yml>

Reference consumers: `/workspace/docker-devkit`, `/workspace/unity-devkit`. Docs: docs.zizmor.sh
(audits + configuration pages).

CAUTION: checking zizmor's exit code through a pipe (`zizmor ... | tail; echo $?`) reports the
exit of `tail`, not zizmor — this produced one wrong conclusion during the audit (see fact 1).
Use `${PIPESTATUS[0]}` or no pipe.

## Verified facts (do not re-derive)

1. **Exit status: nonzero on ANY finding.** One low-severity self-repository finding → exit 12;
   with high-severity findings present → 14; clean → 0. An earlier session claim that low/help
   findings are "advisory-only, exit 0" was a pipe artifact and WRONG. The runner
   (`src/release_devkit/zizmor.py`) turns any nonzero exit into lint failure, so a rule whose
   findings are merely low-severity still needs `disable` (or `--min-severity`, fact 2) to stay
   green.
2. **CLI knobs:** `--min-severity <level>` filters findings below the level entirely (not
   printed, no exit effect); `--no-exit-codes` makes findings not affect exit (rejected — hides
   real failures); personas `regular`/`auditor`/`pedantic`.
3. **Config knobs:** `ignore` supports `filename.yml[:line[:column]]` — line scoping exists but
   is brittle across consumer line drift. `disable` is documented by zizmor as last resort
   (disabled rules vanish from ignored/suppressed counts).
4. **What each relaxation actually suppresses** (raw findings, no config):
   - `unpinned-uses` (high): every `uses:` in the fleet — checkout@v5, setup-uv@v7,
     create-github-app-token@v3, NuGet/login@v1. Blanket hash-pin default since zizmor 1.20.
   - `self-repository` (low): one finding per `uses: ./.github/actions/setup-release-devkit`
     (6 each in docker-devkit / unity-devkit). Audit introduced in zizmor 1.30.0.
   - `dangerous-triggers` (medium): merge-gate.yml's `workflow_run`.
   - `github-app` (high): the mint step — "app token inherits blanket installation permissions".
   - `template-injection`: merge-gate.yml:38 `--head-sha` interpolation (high) in all repos;
     unity integrate.yml:89 matrix (medium) and :92 needs-outputs (info). NOT fired in
     release-devkit's or docker-devkit's integrates — the integrate.yml ignore only does work
     for unity-shaped consumers.
5. `unpinned-uses` supports `config.policies` (per repository-pattern: `hash-pin` | `ref-pin` |
   `any`; implicit `"*": hash-pin`). A bare unpinned `uses:` does not even parse in zizmor 1.30
   (model error); branch pins satisfy `ref-pin`; `"*": ref-pin` greens the fleet.
6. **github-app conformance verified end to end:** flat inputs `permission-contents: write` +
   `permission-pull-requests: read` on the mint step silence the audit. The action supports them
   natively (generated `permission-*` inputs block in its action.yml), and actionlint 1.7.12
   accepts them (input validation confirmed active via bogus-input control). The `permissions:`
   map input does NOT silence zizmor 1.30 — only the flat spelling works.
7. **template-injection conformance:** env indirection (`env: X: ${{ ... }}` + `$X` in run)
   silences the audit — verified; it is zizmor's documented remediation. Conflicts with the org
   grammar law (GitHub facts never ride the step env block; `--head-sha` is deliberately a flag).
8. **`$/` self-repository syntax** (GA 2026-07-30): `uses: $/...` resolves to the workflow's own
   repository at the exact running commit, no checkout required, works in steps/composite/nested/
   reusable calls; requires runner ≥ 2.336.0; GitHub treats it as pinning (SHA-pin policies
   become enforceable for self-references). Fork caveat: resolves the merge ref (fork content) —
   not a fork hardening. zizmor 1.30.1 parses `$/` fine. **No released actionlint accepts it**
   (1.7.12 rejects "ref is missing"; changelog through v1.7.12 — the newest, predating GA — has
   zero mentions). The runner fleet is self-hosted (infra-github-runners): verify its version
   before any flip.
9. **actionlint live-value inventory** (all probed): expression/matrix/needs reference errors
   (unique value concentrated on paths that never execute pre-landing: release.yml, merge-gate's
   workflow_run wake); runner-label typos (only validator — GitHub silently queues forever;
   custom labels declared via `.github/actionlint.yaml`, unity-devkit carries one); input-typo
   validation for only 2 of the org's 4 actions (checkout and create-github-app-token yes;
   setup-uv and NuGet/login absent from the bundled dataset — `enable-cach:` typos sail
   through); shellcheck integration INERT (no shellcheck binary in the environment — obvious
   shell bugs pass clean); the untrusted-inputs check is the ONLY injection coverage inside the
   two zizmor-ignored files (integrate.yml, merge-gate.yml).
10. The offline persona skips API-dependent audits (impostor-commit, known-vulnerable-actions) —
    the "N suppressed" counts in every run.
11. No repo in the org runs Dependabot (only vendored node_modules copies). `zizmor --fix=safe`
    can perform initial hash-pinning mechanically.
12. **Platform fact:** in-Actions event-driven green-detection is `workflow_run` or nothing —
    `check_run`/`check_suite` never fire for Actions-created checks, and no `pull_request`
    activity type fires at checks-green. Any design avoiding workflow_run replaces the wake with
    a poll.
13. The zizmor runner's input is `.github/workflows` only — wrapper action files under
    `.github/actions` escape the audit (verified: wrapper-internal unpinned uses flagged only
    when the input is widened to the repo root). actionlint DOES follow local actions
    transitively.
14. **Empirical template-injection taint map (zizmor 1.30.1, expression probes):** fires HIGH —
    `github.event` free-text fields (PR title), `github.ref_name`, `github.actor`, and the ENTIRE
    `github.event.workflow_run.*` context (coarser than `pull_request`: `workflow_run.head_sha`
    is tainted by context while `github.event.pull_request.head.sha` alone is recognized
    immutable); the merge-gate `||` finding is driven by its workflow_run half. Fires MEDIUM —
    `matrix.*` only when the matrix is dynamically composed (`fromJson(needs.…)`); statically
    written matrices do not fire. Fires INFO — `needs.*.outputs.*`. No finding:
    `github.event.pull_request.head.sha` alone, `github.event.pull_request.number`, `github.sha`,
    `github.repository`. Shell quoting of the interpolation changes nothing. Env indirection is
    clean — env values are data by construction: bash parses the literal script into commands
    before parameter expansion, so tainted text can arrive only as word content, never as
    operators.
15. **The unity integrate matrix finding was substantively correct, not a false positive:**
    `projects.py` validates `unity-devkit.json` `name` as non-empty only (no charset law), and
    the matrix derives from the PR head tree, so a PR author controls `matrix.project-name` text
    verbatim — the earlier "matrix verbs emit facts only ⇒ org-authored facts" framing held for
    grammar, not content. D7's env indirection makes the vector inert; source-side charset
    validation is therefore unnecessary for injection safety.
16. **checkout v7 pwn-request defaults (GA 2026-06-18):** `actions/checkout` v7 refuses
    fork-PR-head checkouts in `pull_request_target` and `workflow_run` workflows by default
    (the latter only when `workflow_run.event` is a `pull_request*`) — fork `repository:`,
    `refs/pull/N/{head,merge}` refs, and head/merge-SHA refs, with opt-out via the deliberately
    alarmed `allow-unsafe-pr-checkout`. Bites when D2 pin bumps cross v7: fork-shaped wakes fail
    the checkout itself (our fork path already fails head→PR resolution; this is platform-native
    belt-and-braces arriving on its own — the platform's grain is hardening against the
    workflow_run shape).
17. **The fact-12 wall is workflow-trigger-scoped.** GitHub App webhooks receive
    `check_suite`/`check_run` completed events for Actions-created checks (the documented
    CI-server pattern; the bors-ng/Kodiak/Mergify lineage) — an external event-driven lander is
    possible without polling. tide (pure poll, 1m sync) and Zuul (webhooks + speculative gating)
    anchor the central-service tier. Parked with P3's rejected branches.
18. **GitHub merge queue supports merge/rebase/squash methods** (queue-controlled; the
    2023-era merge/squash-only limitation is gone) — recorded against any D5 revisit. The queue
    still cannot express head-identity certification: it lands merge-group trees, never the
    byte-for-byte certified PR head.
19. **zizmor's repo-root scan respects .gitignore** (verified on Make-it-Sing: the gitignored
    Unity `Library/PackageCache` tree — vendored livekit packages carrying their own
    `.github/workflows` — is not collected; only the repo's own canonical files + wrapper were
    audited). The widened runner input is safe on Unity repos: CI checkouts carry committed files
    only, and locally the ignore keeps generated trees out of the audit.

## Operator decisions (2026-10-09, binding)

D1. **Hash-pin everything, third party included.** Supersedes the recorded "no SHA-pinning /
    out of scope" positions (plan-evergreen-ci pre-split backup line ~99, the zizmor bullet in
    release-devkit-finish.md, and the zizmor.yaml comment — now marked SUPERSEDED). The
    `unpinned-uses: disable` stanza dies with the implementation.
D2. **Pins centralize in per-repo composite wrappers**, one per third-party action
    (`.github/actions/{checkout,setup-uv,mint-token,nuget-login}/action.yml`), mirroring the
    setup-release-devkit pattern: SHAs live only inside wrappers; call sites use local refs
    (eventually `$/`). Obligations: inputs/outputs explicitly forwarded (composites have no
    passthrough); the checkout wrapper defaults `persist-credentials: false` (persistence
    becomes an explicit call-site opt-in); the zizmor runner input widens to the repo root
    (fact 13) or the wrappers escape audit; lint constants (`CHECKOUT_USES`, `SETUP_UV_USES`,
    `DEVKIT_WRAPPER_USES`) and tests retarget to wrapper call sites; **consumer file change +
    devkit re-pin must be atomic per repo** — old-pinned lint demands the `@v5`/`@v7` tag
    spellings, so the flip rides the consumer sweep (ci-refresh-seed.md), not a file-only PR.
D3. **`$/` adoption: yes, when both gates pass:** an actionlint release supporting `$/`, and
    the runner fleet verified ≥ 2.336.0. The flip changes call sites + lint constants + tests
    and deletes the self-repository disable in the same change. Interim: keep `./` and the
    disable — it is load-bearing (fact 1). Considered, not adopted: runner flag
    `--min-severity medium` fleet-wide (would make low-severity advisory everywhere, enabling
    this rule without the disable) — a fleet policy choice to revisit deliberately, not slip in.
D4. **actionlint: keep.** Its live value is facts 9's list; reassess only if upstream stalls on
    `$/` support for months. Replacement stack if ever ditched (strictly worse): in-lock schema
    validation (e.g. check-jsonschema against GitHub's workflow schema) and living without
    expression typing.
D5. **No GitHub merge queues — permanent.** Standing principle: keep the system as decoupled
    from GitHub Actions as possible.
D6. **github-app: conform.** Flat `permission-contents: write` + `permission-pull-requests:
    read` inputs on the mint step (fact 6's verified spelling — the only form that silences
    zizmor 1.30 and passes actionlint 1.7.12); the ignore stanza dies with the implementation.
    The two scopes cover the verb's whole footprint (landing push / branch delete / draft
    delete = contents: write; gh pr view/list = pull-requests: read); the evergreen-dev ruleset
    bypass is identity-level and unaffected by scoping. No tradeoffs remain. Sequencing: this
    repo's own merge-gate.yml conforms first and its next landing (finish-plan PR-2) is the live
    canary for scope coverage, then the file change rides the consumer sweep atomically per
    repo with the re-pin (the D2 pattern).
D7. **Grammar law amended: tainted-source expressions consumed by `run:` ride the step env
    block.** The old law ("facts never ride the step env block") predates knowing the
    template-injection class (the parse-order mechanism, fact 14); zizmor's documented remediation
    — env indirection — is now the org pattern. New law: ambient facts stay ambient (no
    interpolation anywhere); attacker-controllable expressions a `run:` step consumes ride the
    step env block with the run line referencing the variable (`--head-sha "$HEAD_SHA"` — the
    flag stays the verb API, env is the transport); known-immutable contexts (fact 14's no-fire
    list: `github.event.pull_request.head.sha` alone, `.number`, `github.sha`, `github.repository`)
    may interpolate directly. Applies to the three tainted shapes: merge-gate's `--head-sha` (via
    its workflow_run half), unity's matrix `--project`, unity's needs `--license`; both
    template-injection ignore entries die with the implementation. Doc statements riding the
    sweep: the AGENTS.md grammar paragraph, unity-devkit's "env vars carry secrets only" line and
    consumer CI template. Source-side charset validation of unity project names dropped as
    unnecessary (fact 15).
D8. **P4 parked: supply-chain scanning is its own future initiative.** Operator scope ruling
    (2026-10-09): the static analysis components of this audit complete first; the non-static
    question (offline persona vs online) is deferred whole to `supply-chain-control.md` — a
    parked design record carrying the taxonomy (static gates / non-static senses), the agreed
    three-lane shape, the open sub-decisions, and the resume trigger (backlog item 1 through the
    consumer sweep). Meanwhile the offline persona stands as committed; the skipped audits
    (`impostor-commit`, `known-vulnerable-actions`) stay skipped, and the interim risk (SHA pins
    enter the fleet with no automated real-release verification) is accepted and recorded there.
D9. **P5 parked into the same note — one comprehensive supply-chain initiative.** Pin-bump
    maintenance is the chain's restocking half; it is deferred with the sensing half into
    `supply-chain-control.md` (titled and scoped there: link-by-link map of the org's chain,
    which links are already controlled, which are parked). Welded by tooling: Dependabot bundles
    advisory sensor + version actuator, so choosing an actuator alone pre-shapes the sensor and
    topology choices — one initiative decides them together. Interim policy (binding): all pins
    bump by operator act, manually; see the note's Interim policy section for the ossification
    risk and the items currently gated on a bump.
D10. **P3 resolved: keep the per-repo lander; label-only wake.** Delete `workflow_run` from
    merge-gate.yml — the sole wake is `pull_request: [labeled]` on `ready-to-merge`, and the
    label changes meaning from adjective (standing intent, never re-applied) to verb (attempt
    now): a poke before green or before rebase fails loudly, and landing = remove-and-re-add the
    label once green AND rebased. The UX cost is accepted. Soundness rests on two verified
    properties: the all-green battery already excludes the merge-gate check by name
    (`GATE_CHECK_NAME`, merge_gate.py:79), so failed early pokes cannot poison re-pokes; and the
    wake carries no authority — every precondition (label, OPEN, checkout-is-head, all-green,
    rebased-onto-dev) is re-derived at execution, the identical safety envelope; only wake
    coverage shrinks. The P3 attack-class audit transfers unchanged (every traced class is
    verb-side, wake-independent): no fork/PR code execution (pinned actions + pinned devkit;
    git merge runs no tree-controlled code; `persist-credentials: false` lint-enforced); no
    untrusted artifacts consumed; head_sha is hex and re-verified via the API (the wake is a
    doorbell, not a source of truth); wake-alone merge impossible (label consent is
    privileged); fork PRs cannot carry the label and head→PR resolution fails outright.
    Obligations: the verb's pending branch (merge_gate.py:84–86, "the other
    wake will land it", exit 0) becomes a loud refusal — under label-only it is a silent stall;
    the dry-run's spelling of the same message updates; the workflow's dual-payload machinery
    simplifies (`if:` → label check only, checkout ref and `HEAD_SHA` → the
    `pull_request.head.sha` no-fire spelling, concurrency group loses the `||`); the lint's
    merge-gate found-file contract rewrites (workflow_run wake on Integrate's name →
    labeled-only); the AGENTS.md landing-changes paragraph rewrites (two wakes → one; "never
    needs re-applying" dies); the label's GitHub description (infra-github-org LabelSpec)
    updates to the verb meaning. Relaxations: dangerous-triggers and the merge-gate
    template-injection stanza die with this change (the finding was the workflow_run half —
    fact 14); with D6, D1/D2, and D3 the ledger reaches zero. Residuals unchanged: vacuous
    green, the mint step (D6-scoped), the two-poke merge race (second push loses loudly).
    Rejected branches, with reasons: GitHub merge queue (cannot express head-identity
    certification — fact 18; moves landing policy into forge config; still Actions-resident —
    contra D5 twice over); external lander daemon (new always-on host; the App PEM wants a home
    disjoint from runner code-execution boxes, i.e. a dedicated server — rejected as new
    infrastructure); central scheduled lander (fleet-wide singleton stall risk; the 60-day
    scheduled-workflow auto-disable on quiet repos; the org's first runtime cross-repo
    coupling); per-repo cron (the same auto-disable footgun × fleet size, ~4.3k polling runs/
    day); label-waiter and integrate-tail variants (more machinery buying UX this decision
    deliberately declines). D5 stands, now better grounded: the queue is rejected on
    head-identity and policy-ownership grounds in addition to coupling. Fact 12 is declined,
    not solved — the human is the green-and-rebased detector; the verb re-verifies regardless.
    The design space is two families (a forge event wakes privileged code vs a lander that goes
    and looks); label-only is the cleanest member of the first family — maintainer-gated wake,
    no-fire payload spelling, OWASP-blessed trigger — and the only one that is per-repo, Family
    A, and free of new footguns.

## Implementation backlog (dependency order)

1. DONE for this repo's own files (2026-10-09 item-1 session; see the final Done section). The
   consumer-sweep half — wrappers, mint scoping, env-indirect unity's two tainted shapes (matrix
   `--project`, needs `--license`), lint retargeting, doc statements (unity-devkit's AGENTS.md env
   line + consumer CI template), stanza removals inherited via the re-pin — rides
   ci-refresh-seed.md atomically per repo.
3. DONE for this repo's own files (same session). The consumer half (each repo's merge-gate.yml
   flip, label description already landed fleet-wide via infra-github-org dc4f9e0) rides the same
   sweep.
4. D3 `$/` flip: watch actionlint releases; verify the runner fleet version; flip spelling and
   delete the self-repository stanza in one change.

## Done (2026-10-09 session)

- `src/release_devkit/zizmor.yaml` (now `verbs/zizmor.yaml` after the runner fold into
  lint_workflows): comments only — the self-repository disable is documented
  as load-bearing with its lift conditions, and the unpinned-uses comment is marked superseded
  by D1. No relaxation changed hands; all three reference repos exit 0 under the committed
  config (verified), and the full test suite passes (175).

## Done (2026-10-09 continuation session)

- Decisions: D6 (github-app: conform the mint step), D7 (grammar law amended — tainted-source
  expressions ride the step env block; probe facts 14–15 recorded, the unity matrix finding
  reclassified as substantively correct), D8/D9 (supply-chain sensing AND restocking parked
  whole into `supply-chain-control.md` — scope map, three-lane shape, topology-trio resume
  agenda, binding interim policy of manual operator pin bumps).
- Code folds: `zizmor.py` and `actionlint.py` deleted; both runners and their machinery live in
  `verbs/lint_workflows.py` (constants `ZIZMOR_CONFIG`, `ACTIONLINT_*`); zizmor config moved to
  `verbs/zizmor.yaml`; pyproject wheel-include updated. Ruff, 175 tests, basedpyright strict —
  all green. No relaxation changed hands.

## Done (2026-10-09 P3 session)

- Research: the merge-when-green landscape verified — bors → bors-ng (deprecated 2023 in favor
  of the native queue) → GitLab merge trains → GitHub merge queue (GA 2023) is the convergence;
  tide (1-minute poll loop) and Zuul (webhook + speculative gating) anchor the central-service
  tier; in-repo bots converge on label-trigger + in-job wait or the native auto-merge handoff —
  workflow_run merge bots are essentially unused in the wild. Facts 16–18 recorded; the design
  space mapped to two families (a forge event wakes privileged code vs a lander that goes and
  looks). D10 recorded: P3 resolved as the label-only merge-gate wake. No relaxation changed
  hands; all stanza removals ride backlog items 1 and 3.

## Done (2026-10-09 item-1 session)

- Backlog items 1 and 3 executed for this repo's own files (commits `1fb8e22` prose, `f970dbb`
  code, `3c5dc0e` CI files on `lint-trim`; the consumer halves ride ci-refresh-seed.md):
  - D1/D2: three per-repo composite wrappers in the canonical set — `.github/actions/checkout`
    (actions/checkout@`fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09`, defaults
    `persist-credentials: false`), `.github/actions/setup-uv`
    (astral-sh/setup-uv@`37802adc94f370d6bfd71619e3f0bf239e1f3b78`), `.github/actions/mint-token`
    (actions/create-github-app-token@`bcd2ba49218906704ab6c1aa796996da409d3eb1`); the
    `.github/actions/nuget-login` wrapper (NuGet/login@`8d196754b4036150537f80ac539e15c2f1028841`)
    is canonical for nuget-declaring consumers, unused in this repo. `CHECKOUT_USES` /
    `SETUP_UV_USES` retargeted to the wrapper call sites (direct `actions/checkout` uses are now
    findings); the zizmor runner input widened to the repo root. Wrapper SHAs resolved via
    `git ls-remote` peeled tags at authoring time (manual operator-pin policy, D9 interim).
  - D6: the mint wrapper hardcodes `permission-contents: write` + `permission-pull-requests:
    read`; call sites forward only `app-id`/`private-key` (composites cannot see `vars`/`secrets`
    contexts — forwarding is required, not stylistic).
  - D10: merge-gate.yml wakes on the label alone — `workflow_run` deleted, `if:` label-only,
    concurrency `merge-gate-${{ github.event.pull_request.number }}`, checkout and `--head-sha`
    both on the no-fire `pull_request.head.sha` spelling, no env indirection. merge_gate.py's
    pending branch is now a loud refusal ("remove and re-add the label once green"); the dry-run
    spellings updated. The lint contract rewritten: labeled-only wake, `workflow_run` forbidden,
    the cross-file Integrate-name check deleted. The label description flipped in
    infra-github-org (`dc4f9e0`; live state updates at the operator's next `pulumi up`).
  - zizmor.yaml: `unpinned-uses`, `github-app`, `dangerous-triggers`, `template-injection`
    stanzas deleted; `self-repository` is the sole surviving relaxation. Ledger: one of five.
  - Self-hosting: integrate.yml gains the `lint-workflows` job (completing finish-plan PR-2's
    self-lint half); self-pin `ad42152` → `f970dbb` (the commit carrying the new law) in the
    same atomic change.
- Verified: raw zizmor on the conformed repo reports exactly 9 self-repository (low) findings —
  one per `./` wrapper use — and nothing else (exit 12, fact 1 confirmed); the configured run
  exits 0. actionlint 1.7.12 accepts the wrapper files and the mint permission inputs (follows
  local actions). Ruff, basedpyright strict, 174 tests green.
- The finish plan's "reference repos MUST stay green" rule is superseded by D2 atomicity: the
  new law intentionally reddens pre-sweep consumers — docker-devkit/unity-devkit fail the new
  lint until their sweep step flips their files with the re-pin.
- Fact 19 recorded (zizmor respects .gitignore — repo-root scans on Unity repos stay out of
  vendored/generated trees).
