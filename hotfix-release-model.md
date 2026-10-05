# The hotfix release model (parked design record)

Implementation deferred by operator ruling: the design is verified mostly
additive, the current release flow stays untouched, and this file is the
record to resume from. Nothing here is built or load-bearing yet.

## The model in force today

`dev` is evergreen: PRs to it are certified by Integrate at the exact head
SHA, and the merge-gate/merge-bot lander fast-forwards `dev` to certified
heads only. Promotion is an operator act: push a chosen certified dev SHA to
`main` (`git push origin <sha>:main`). A `main` push fires `release.yml`,
whose `release` verb computes the plan from the per-package tag ledger plus
path-diff, publishes changed packages, pushes per-package version tags, and
cuts the GitHub Release. Dev pushes publish prereleases. The standing
release-PR flow (`ensure-release-pr`) is retired separately and near-term;
its removal is a prerequisite recorded elsewhere, not part of this design.

## The gap

CI-green is not promotion-ready: dev can be green and still mid-flight. When
something already shipped is broken and dev is not promotable, the in-model
floor is finish-or-revert the in-flight work, one Integrate, one push — too
slow during a fire. The forbidden shortcut is any main-only commit: commits
that exist only on `main` break fast-forward promotion forever after (the
ancestry disease; unity-devkit's click-merged release PR is the live scar,
repaired by a one-time reconciliation merge).

## The design: upstream-first release branches

Nouns: `dev` is the workshop; `main` is the shelf (what the world runs);
tags are the receipts (each release is a name stuck on one exact commit, and
the tag ledger is the version source of truth).

The fire runbook:

1. The fix lands on `dev` like any change and is certified green. Fixes
   always live on dev first — never only on the release branch.
2. Cut a release branch at the promoted tip (a copy of `main`), typically
   retroactively from the last release tag; nothing stands between fires.
3. Cherry-pick the certified fix commits onto it. CI runs on the release
   branch too (the full Integrate battery, plus the hygiene check below).
4. The operator manually verifies, then performs the deliberate act that
   cuts the release (see the trigger design below).
5. The tagger computes next-in-line per affected ledger and pushes the
   version tag(s). The tag push triggers publishing.
6. Delete the release branch whenever. Nothing ever merges anywhere: the fix
   is on dev from step 1, so the next promotion absorbs it by construction.

Laws:

- **Upstream first, one-way cherry-picks.** Fixes ride dev, then get
  cherry-picked to the release branch; never the reverse. Fixing on the
  branch and merging back relies on remembering — a forgotten backport is a
  resurrected bug at the next release. (Linux kernel, GitLab, Google, and
  Red Hat all run this exact rule.)
- **Cut from a promoted tip, delete when done.** A tag-triggered workflow
  executes the workflow file as committed at the tag's target, so the
  release branch must always carry current wiring. Release branches are
  never merged back.
- **Fire-only.** The release branch is the exception path, never the habit.
  If releases start being assembled by cherry-pick selection meetings, the
  trunk is not deployable — that is the anti-pattern, and promotion-from-dev
  is the structural answer.
- **Regression test behind.** Every hotfix leaves a regression test in dev
  CI. A human verification is true at one commit; a test is true at every
  commit after it.
- **Hygiene is mechanical.** The verify step refuses to publish any tag
  whose target contains commits whose patch-ids are not present on dev
  (`git cherry`-equivalent over `main..tag`).

## The unified release trigger

One trigger type publishes: a tag push. Both paths share the same shape —
deliberate human act, then the robot names, then the tag fires delivery:

```
normal:  operator pushes <sha>:main        ->  tagger tags  ->  tag push -> verify -> publish
hotfix:  operator dispatches on release/*  ->  tagger tags  ->  tag push -> verify -> publish
```

- The tagger computes next-in-line per affected package ledger from
  path-diff (multi-ledger repos make this inherently a robot job — which
  ledgers a change touches is not a human decision), and pushes tags with
  the merge-bot App token. A tag pushed with the job's built-in
  `GITHUB_TOKEN` triggers nothing — GitHub's recursion guard — so the App
  token is load-bearing in both paths.
- Tags are machine-owned: only the App pushes tags, and the tag ruleset
  locks the tag namespace to the App alone. The operator's release acts are
  exactly two: promote (push) and cut (dispatch).
- No-op promotions tag nothing: the tagger path-diffs, finds no changed
  ledger, and no publish run exists at all.
- Verify (same gate for robot and human acts): tag matches a declared
  ledger prefix; version is next-in-line (no skips, no re-cuts); the target
  has a green Integrate run on its ref; upstream-first hygiene holds.
- Rejected alternative: human-pushed tags. Hand-computing versions under
  fire invites fat-fingered tags, and multi-ledger path-diff makes it
  unreliable outright. An earlier draft leaned on GitLab's "tags should be
  set by users rather than CI" guidance; that concern targets careless
  auto-versioning, and here the deliberate act sits before a ledger-verified
  tagger.

## Ruleset shapes (to author when built)

- `main`: push actors restricted to the operator, require linear history,
  block force pushes, block deletions. Linear-history plus no-force is
  fast-forward-only in practice; actors make promotion an operator monopoly.
- `release/**`: the same family.
- tags: App-only push.

## Why this can sit unbuilt (verified, not assumed)

- The version ledger is tag-glob, not reachability-based (`fetch-tags`,
  patch-auto within the declared line): a release-branch tag is a global
  ref, and the next `main`-based publish increments past it. Monotonic, no
  collisions, no force-reset temptation.
- Path-diff collapses correctly: the release branch's base is the tagged
  promotion tip, so its diff against the ledger is exactly the fix; after
  absorption, dev's diff against the branch tag is only post-fix work. No
  double publish.
- Registry identity is filename-scoped (npm/nuget bind owner/repo plus
  workflow filename; PyPI binds repo/workflow): the same `release.yml`
  publishing from a release branch keeps every trusted-publisher binding.
- Lead times before the first fire: the workflow edits must be promoted, and
  the tagger/verify code must land here with consumer wrapper SHA bumps
  (this repo is consumed by pinned SHA clone, never published).

## Open when resumed

- Tagger workflow shape: the `main`-push arm and the dispatch arm, and where
  the tagger lives relative to `release.yml`'s job set.
- Retrofit of the two legacy `workflow_run`-shaped repos (unity-devkit,
  StatefulUnity) onto the unified trigger.
- Release branch naming (`release/<major.minor>`, one branch per patch
  series, stacked fixes) and the retroactive-cut convention.
- Interaction with the prerelease surface on dev pushes.

## Research anchors

- https://trunkbaseddevelopment.com/branch-for-release/ — one-way
  cherry-picks, Google's snapshot-plus-cherry-picks release branches,
  retroactive branch cut from the release tag, delete-never-merge.
- https://about.gitlab.com/topics/version-control/what-are-gitlab-flow-best-practices/
  and the GitLab flow doc — upstream first (Google/Red Hat), releases are
  tags, every cherry-picked fix is a patch bump via a new tag.
- https://beyond.minimumcd.org/docs/anti-patterns/branching-integration/cherry-pick-releases/
  — the fire-only guardrail.
- https://paulhammant.com/2026/06/22/the-cherry-pick-asymmetry/ — the
  release branch's verification is legitimately the stronger certificate;
  regression-test-behind.
