# Unity license & runner architecture (parked design record)

Implementation deferred by operator ruling (2026-10-10): the design below is settled but
unbudgeted, and the current architecture — `UNITY_*` secrets as job env, per-repo license
caches, restore-or-activate in every build job — remains in force untouched. Nothing here is
built or load-bearing. This note is deliberately absent from
`plan-devkit-rearchitecture.md`: the plan executes Unity-agnostic with the current
secret-threading, and this design lands (or dies) as its own initiative.

## Why the fleet exists at all

`infra-github-runners/SPEC.md:5`: Make-it-Sing went private → hosted runners on private repos
leave ~14 GB free disk → the `unityci/editor:*-android-*` image (~14 GB extracted) exhausts
disk during "Initialize containers", before any step runs, so no in-job cleanup can rescue it
→ 2× Hetzner `ccx23`, runner group `self-hosted-unity`, label `unity`, one job slot per box
(IL2CPP contention, SPEC.md:29). Public repos get big free hosted runners where the same
Unity build runs fine (proven in placeframe's public CI) — the fleet exists because of
privatization, not Unity per se.

## Current-state warts (the redesign's motivation)

`unity-devkit/packages/python/unity-devkit/src/unity_devkit/license_restore.py`:
restore-or-activate loop (`:33-56`), cold activation passing `UNITY_EMAIL/PASSWORD/SERIAL`
as editor CLI args — ps-visible (`:59-64` area), per-day cache tag `v-YYYY-MM-DD` (`:77`) with
the midnight cliff, jittered restore-retry arbitrating sibling-leg races, per-REPO cache
namespace (`--registry ghcr.io/{owner}/{repo}`) ⇒ up to N cold activations per day for one
org-wide license.

The structural flaw: the license credentials are GitHub-resident secrets — the
workflow-as-secret-broker pattern. Any compromised member account (GhostAction shape) authors
a workflow in any repo carrying the secrets and exfiltrates them; fork PRs are safe (zero
secrets, read-only token) but same-repo PR runs see everything.

## Target design (settled 2026-10-10, operator-locked through iteration)

### Runner allocation

- The fleet serves ONLY Make-it-Sing's Unity builds. Every public repo — first-party and the
  other org's — builds Unity on GitHub hosted runners.
- No cross-org runner registration (mechanically possible via their-org registration tokens,
  but superseded: public repos need no fleet). The dedicated-boxes vs dual-runner-processes
  question dies with it. The dispatch/build-gateway pattern (their repo pings a workflow in
  our org; the whole battery runs under our spelling; results report back as check runs) is
  shelved as the shape for orgs we do NOT trust.

### Credentials

- `UNITY_*` vanish from GitHub entirely — every repo's secrets, every workflow env block.
- They live as machine-resident files on the two boxes, same class as hcloudToken /
  githubAppPrivateKey: supplied at stand-up, never committed, consumed only by the refresh
  path.
- The GitHub App private key (cross-org mirror writer, below) is machine-resident the same
  way. No App key ever enters any GitHub secret store, ours or theirs.

### License cache and the uniform read

- One org-shared private package: `ghcr.io/outernet-foundation/unity-license`. Per-repo
  namespaces die. Rolling validity tag (the per-day tag and its midnight cliff die);
  freshness metadata rides the artifact.
- EVERY consumer — first-party or other-org — reads with the ambient `github.token` + a
  same-org "Manage Actions access" read grant. Identical single step; zero special-casing in
  `build-unity.yml`. The ambient token is born and dies with the job — nothing exfiltratable.
- The GitHub App can NEVER be the in-job mechanism, anywhere: minting an installation token
  requires the App private key, so in-job minting means the key lives in GitHub secrets — a
  cross-org master credential brokered by any workflow that can read it. (This kills the
  "install the App and mint in jobs" idea for both orgs; it was mechanically broken for the
  other org anyway — installing grants permission, never the key.)

### Cross-org (the trusted political org)

Their repos are public → hosted runners only. The nightly cron (below) mirrors the license
into a package in THEIR org; their repos read their own copy ambient + their own grant.

```
nightly cron, runs on OUR fleet box (trusted spelling, default branch)
  activate with box-resident Unity creds (unity-devkit verb, pinned)
  ├─ oras push → ghcr.io/outernet-foundation/unity-license
  │              (ambient devkit-repo token + write grant)
  └─ mint with box-resident App key (App installed in their org,
     Packages: write) → oras push same .ulf
              → ghcr.io/their-org/unity-license      (the mirror)

every Unity build job, both orgs:
  pull .ulf from MY org's package with the ambient token  (one step, no branches)
```

- Their entire involvement: install the App once; grant their repos read on their own
  package (one Pulumi snippet in the org-management instructions we already hand them).
- Mirror lag ≤ one cron tick; acceptable.
- Verify at implementation: installation-token push into their org's ghcr namespace creates
  the package under the org as expected.

### Builds are strictly restore-only

Every Unity build job everywhere pulls the `.ulf` as binding-owned provisioning (a step inside
`build-unity.yml`) or fails loudly. No build job ever activates; no lazy self-heal anywhere;
no `license-check`/`refresh-license` job pair in the reusable. Consequence: no consumer's
workflow graph touches the fleet, so no consumer needs runner-group membership.

### Refresh = scheduled workflow in github-actions-devkit

`.github/workflows/unity-license-refresh.yml`, `on: schedule`, daily.

Why there: the repo owns `build-unity.yml` and the license contract (contract changes and
refresh changes land in one PR); scheduled events execute default-branch spelling only —
trusted by construction, no PR, no consumer YAML, no self-checkout dance; being public costs
nothing (no secrets in the file; only the landed spelling can demand the fleet).

Job shape:

- `runs-on: [self-hosted, unity]`, pinned `unityci/editor` container.
- Activate via the pinned unity-devkit activation verb, box-resident creds.
- `oras push` both targets (own org + mirror), rolling tag.
- Verify what it pushed: restore it back AND open the editor with it (unity-devkit harness)
  so "succeeded" = "license works".
- `concurrency: unity-license-refresh`, no cancel — a slow run queues; the queued run
  re-checks and usually no-ops.

Cadence: daily, deliberately conservative. Confirm ONCE against the `.ulf`'s own stated
validity window (read the XML's dates — one file read, not a study). Do not go finer: each
refresh is a real activation and Unity accounts have activation-count friction; daily
presumably sits at many-times margin inside a multi-day-to-weeks window.

Self-keepalive (the 60-day scheduled-workflow auto-disable): the workflow's final step, after
a SUCCESSFUL refresh, pushes a heartbeat note to a dedicated `keepalive` branch. Keeps itself
alive (no third-party keepalive action, no bot account); a branch push dodges default-branch
protection; keepalive-on-success-only is correct — a broken cron should die, having alarmed
loudly long before. The heartbeat branch doubles as the refresh audit trail. Backstop that
costs nothing: if disable happens anyway, licenses expire within the validity window and
builds go loud-red — degraded, never silent, never corrupt. Verify at implementation whether
the activity counter resets on any push or only default-branch pushes; fallback is a
heartbeat commit to the default branch with a ruleset carve-out.

### Prerequisites and operator ledger

- `github-actions-devkit` joins the `self-hosted-unity` runner group — it becomes the only
  public door to the fleet, and its two doors are exactly:
  1. Org-wide push ruleset path-restricting `.github/**`, bypass = operator (closes the
     compromised-member path: member authors fleet-scheduling spelling on the default branch).
  2. Fork-approval tier "all external contributors" on public repos (an APPROVED fork PR's
     spelling can demand `runs-on: self-hosted`; approval is the human gate. The default
     first-time tier is insufficient — repeat contributors auto-run).
- Ledger rows: read grant per first-party Unity consumer; read grant in their org (theirs to
  set); write grant for github-actions-devkit on the license package; App install in their
  org. "Manage Actions access" is UI-only, no API — same operator-ledger class as npm
  trusted-publisher rows; a forgotten grant fails loud (`denied`) on first restore.
- Org settings to verify once: default workflow permissions read-only org-wide; "Allow
  GitHub Actions to create and approve pull requests" OFF.

### Layering law and acceptance criterion

unity-devkit = pure Unity mechanics (activate, verify, build verbs) — GitHub-blind.
github-actions-devkit = all policy and bindings (cron, restore step, grants, mirror).
Dependencies run one way only: devkit → unity-devkit, pinned. The current coupling lives in
`license_restore.py`'s ghcr/ORAS entanglement; this design deletes it (restore becomes a
plain `oras pull` step in the binding; push lives in the cron).

Acceptance criterion for the purification phase: a search of unity-devkit's `src` for
`ghcr|oras|GITHUB_|github.token` comes up empty.

### What landing would touch in plan-devkit-rearchitecture.md (when resumed)

- Phase 2: `build-unity.yml` restore-only provisioning; `UNITY_*` threading dies; fork-lane
  if-gating.
- Phase 3: expanded purification (env contract dies; the grep criterion above).
- Phase 7: ledger rows, ruleset, approval tier, org settings; runner-group posture becomes
  Make-it-Sing + github-actions-devkit only.

## Rejected branches (recorded so they are not re-litigated)

- **Lazy refresh-before-build inside `build-unity.yml`** (license-check hosted +
  conditional refresh-license self-hosted): freshness-by-construction, but it puts the fleet
  in every consumer's graph → org-wide prerequisites and the trusted-spelling self-checkout
  dance. The cron shape narrows the fleet door to one repo. This reversal of the earlier
  no-cron ruling is final.
- **In-job App-token minting (Path A) for reads, first-party or cross-org**: requires the
  App private key in GitHub secrets — the broker flaw in its worst form.
- **Dedicated tiny refresh repo / scheduled repo**: operator-rejected (new repo for one job);
  also the 60-day auto-disable footgun on a quiet single-purpose repo.
- **Cron in Make-it-Sing**: wrong home for org-wide ops. **infra-* repos**: IaC charter.
- **Cross-org runner registration** (trusted org): mechanically possible, but public repos
  need no fleet; the mirror design replaces it entirely.
- **Dispatch/build-gateway for the trusted org**: unnecessary under the hosted-runners
  decision; shelved for genuinely untrusted orgs.

## Residuals and open sub-decisions (the resume agenda)

1. Fork-tier first-party Unity compilation: restore needs package read from a read-only
   fork-run token — uncertain; the eventual answer is the forge thread (next item), not a
   workaround here.
2. Forge thread (parked, `infra-github-runners/SPEC.md:54`): ephemeral single-use runners
   (`--ephemeral` does not wipe the box), network egress allowlisting, boot-time credential
   consumption, per-run cache isolation — the sound-by-construction pattern for untrusted
   Unity builds, an economics decision once the fleet is ephemeral and walled.
3. 60-day activity-rule semantics (any push vs default-branch push) — verify, then lock the
   keepalive shape.
4. Read the `.ulf` validity window once; confirm daily cadence margin.
5. Verify installation-token push creates the package under the other org's namespace.

## Interim policy (binding until this note resumes)

- The current architecture stands untouched: `UNITY_*` secrets as env, per-repo caches,
  `license_restore.py` as-is. No ad-hoc improvements — point any urge at this note.
- Cross-org Unity builds are REFUSED under the current architecture: they would require
  pasting the org's license creds into the other org's GitHub secrets, which is the exact
  flaw this design exists to kill.
- The `UNITY_*`-on-same-repo-PR-runs exposure is accepted and tracked here, not forgotten.

## Resume trigger

Operator budgets a session for it. It may ride the rearchitecture's later phases (see
"What landing would touch") or run as its own initiative; the design above is final-shaped,
so resumption starts at the resume agenda, not at re-derivation.
