# Fork-contribution model (parked design record)

Implementation deferred by operator ruling (2026-10-10): the direction below is settled and
the main plan (`plan-devkit-rearchitecture.md`) was verified compatible with it before
parking — every coupling is additive (retrofit checklist below, so nothing is re-derived).
Nothing here is built. The org-level hygiene settings this model depends on went into the
plan's Phase 7 prerequisites independently (threat-model-justified with or without this
initiative).

## Intent

Repos public; anonymous fork PRs welcome; CI = AI-slop filter — "make the PR author's
machine do work before I even look." Escalation to full trust is ALWAYS a manual operator
action: it guards code-in-privileged-context (indirect PPE), which no detector can vet and
which therefore can never be automated.

## Platform facts this design leans on (verified, load-bearing)

1. `pull_request` runs execute the PR's merge-ref spelling, sandboxed; fork PRs get a
   read-only `GITHUB_TOKEN` and ZERO secrets; approval tiers gate fork workflow runs
   (default "first-time"; "all external contributors" exists; a no-approval tier for public
   repos is believed NOT to exist — flagged verify).
2. **Two-spellings principle**: every PR has its spelling of every workflow (sandboxed) and
   the base's (authoritative). Privileged contexts only ever read the base's. A fork PR can
   rewrite `integrate.yml` freely; its rewrite lives and dies in its own sandboxed run.
3. Same-repo PRs get full secrets + writable token — `GITHUB_TOKEN` ≈ write-access user.
   Private-ish threat = compromised member account (GhostAction: 327 accounts, 817 repos,
   3,325 secrets via pushed "Github Actions Security" workflows).
4. Check runs / commit statuses cannot be fabricated without a write token; gutting
   workflows leaves required checks visibly missing. External CI reports onto fork PR head
   SHAs via check runs (the bors/Jenkins/Cirrus lineage).
5. Runner-group access is repo-granular, NOT actor-granular — fork PR spelling can demand
   `runs-on: [self-hosted, …]`. Defenses: approval tier, group posture, never workflow ifs.

## Fork tier (automatic, sandboxed, hosted runners only)

- Runs the consumer's `preflight.yml` unmodified — already fork-compatible by construction:
  hosted runner, no secrets required, checkout at PR head, script-is-the-slop-filter.
- Docker build WITHOUT push, where applicable (harness provides docker on the runner).
- Write/secret jobs — `mirror`, `build-unity`, `build-docker` push mode,
  `update-pr-draft-release` — `if:`-gated on same-repo
  (`github.event.pull_request.head.repo.full_name == github.repository`), green-skip
  (a skipped need satisfies downstream).
- Fork runs NEVER schedule onto self-hosted runners (hard law) — enforced by the approval
  tier + runner-group posture, never by workflow `if:`s (PR-rewritable, hence worthless as
  the mechanism).

## Escalation = the merge-gate label (the human trust grant)

- Operator labels the fork PR; the gate pushes the PR head to a `try/…` branch in the base
  repo (bors try); `on: push` workflows (base spelling, full trust) run the complete battery
  on the byte-identical tree; results report back onto the fork PR head SHA as check runs
  (trusted-context bot). Evergreen certified-at-exact-SHA survives: the staging ref IS the
  PR's tree.
- Fallback variant: operator pushes reviewed commits into a same-repo branch and re-PRs
  (re-parent).
- A PR-authored (gutted) `merge-gate.yml` cannot merge: fork runs are read-only (cannot push
  `dev`); same-repo member tokens cannot push `dev` (`evergreen-dev` ruleset bypass = merge
  bot only). Merge authority is identity-level at the ruleset, not workflow-level.

## Residuals

- Cache poisoning: zizmor coverage; per-PR caches.
- Hosted-runner slop flood: the approval tier rations; public-repo hosted minutes are
  GitHub's compute.
- Unity fork-tier compilation: impossible while the license is a GitHub secret — parked with
  the Unity redesign (`todo/unity-license-architecture.md`); its forge thread is the
  eventual answer.
- Later, uncontested: auto-close-on-red bots; CONTRIBUTING / social layer.

## Retrofit checklist (all additive — what lands when this resumes)

1. Same-repo `if:` gates on write/secret jobs across consumer spellings + the lint's
   found-file contracts (rides a fleet sweep).
2. An `on: push` (`try/**`) verification trigger — the escalation lane's trusted battery.
3. `merge-gate` fork mode: push head to `try/…`, await the battery, report check runs back
   onto the fork PR head SHA.
4. Expected-check-set assert in `merge-gate` — a gutted fork spelling must never present
   vacuous green (the never-label law is the interim guard, already standing in the plan).
5. Approval-tier + group posture verified live (on the Phase 7 ledger since 2026-10-10).

## Interim policy (binding until this note resumes)

- No fork-PR handling exists: fork PRs to public consumers will show red build legs (no
  secrets). Accepted — do not hand-hold fork PRs into green.
- Never apply `ready-to-merge` expecting the current `merge-gate` to handle a fork PR — the
  fork mode does not exist.

## Resume trigger

Operator budgets a session; natural anchor is after the rearchitecture's fleet cutover
(plan Phase 7) so the if-gate retrofit rides an existing sweep rather than a dedicated one.
