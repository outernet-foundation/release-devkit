# Supply-chain control (parked design record)

Implementation deferred by operator ruling (2026-10-09): all supply-chain questions —
sensing AND restocking — park here as one future comprehensive initiative. The
universal interim answer is manual operator bumping (Interim policy). Nothing here
is built or load-bearing yet. Resume after the zizmor audit's static components
land (zizmor-audit.md backlog item 1); the sensing half meanwhile stands exactly as
committed (`--offline` in `lint_workflows.py` — the API-dependent zizmor audits
`impostor-commit` and `known-vulnerable-actions` simply never run).

## Scope map: the org's chain, link by link

"Supply chain" here is broader than this note's open questions — most links already
have standing controls, recorded so a resuming session doesn't re-derive them:

| Chain link | Standing control | Open question |
|---|---|---|
| Python dependencies | committed `uv.lock` closure (the seal); `>=` floors + relock via the DAG sweep (ci-refresh-seed.md) | none parked |
| Docker base images | digest pins in `workloads/images.lock`; the org mirror namespace (upstream-yank immunity, docker-devkit AGENTS.md) | none parked |
| npm / nuget adoption | exact pins; adoption is a human commit by law | none parked |
| GitHub Actions references | D1/D2 (zizmor-audit.md): SHA pins centralized in per-repo composite wrappers | **both halves below — this note** |

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

## The restocking problem (pin-bump maintenance, was zizmor-audit.md P5)

Post-D2 every repo carries four wrapper SHAs (`checkout`, `setup-uv`, `mint-token`,
`nuget-login`) that never move until someone moves them — the flip side of
hash-pinning: upstream fixes, the `client-id` spelling unblock, and future action
majors all arrive as "someone must bump the SHA," per repo, forever. Pre-D1 tag
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

Scoped reversal, recorded so it is not re-litigated: zizmor-audit.md rejected
`--no-exit-codes` for the LINT gate (correct — a gate must fail); in the sensor
lane it is precisely correct (a sensor must not fail its job, it must speak).

## Open sub-decisions (the resume agenda)

1. Topology: where periodic org-wide jobs live — sensor home, bump machinery,
   and the P3 lander alternatives (zizmor-audit.md P3-B/C) share one "central
   scheduled job vs per-repo cron vs external service" question; decide once,
   together.
2. Stable pre-flight blocking policy: any finding vs high-only (hostage-release
   trade at promotion time).
3. Actuator: Dependabot vs Renovate vs devkit-owned verb — decided with (1) and
   the sensor, per the welding argument above. Interim: `zizmor --fix=safe` can
   perform initial D2 hash-pinning mechanically (zizmor-audit.md fact 11); it is
   a rollout aid, not maintenance.

## Interim policy (binding until this note resumes)

- **All pins bump by operator act, manually, across the board.** Wrappers
  centralize SHAs so a bump is one file per repo per action.
- The interim decays silently into "never": staleness has no alarm. Known items
  currently gated on a bump: the `client-id` mint-step spelling flip (actionlint
  metadata), future `actions/checkout` / `setup-uv` majors, D3's `$/` flip
  (devkit-internal: the `ACTIONLINT_VERSION` pin rides release-devkit's own dev
  flow, not consumer machinery).
- Sensing gap accepted: SHA pins enter the fleet with no automated real-release
  verification (impostor risk). Mitigations: pins are few, centralized, and
  human-copied from upstream release pages at re-pin time.

## Resume trigger

The zizmor audit's static components implemented and swept (zizmor-audit.md
backlog item 1: D1/D2/D6/D7 through the consumer sweep) — then this file joins
the agenda as its own initiative, decided together with P3 (topology) wherever
it resumes; bump machinery may ride the sweep machinery (ci-refresh-seed.md).
