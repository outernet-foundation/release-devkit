# Plan: full release surfaces (packages, apps, image digests)

Locked plan. Every release surface — stable releases, the `dev-builds` dev draft, and `pr-{N}` PR drafts — includes everything produced at its stage: packages (with versions/registry links), app build assets (with download links), and built-image digests (tree-tag + digest). Base/mirror image pins do not appear on any page — they're in source control (`workloads/images.lock`).

## docker-devkit

- In CI mode, distill bake's `--metadata-file` (currently discarded, `build_docker.py:208`) into a digest manifest — structured JSON: `target → {ref, digest, tags[]}` — and push it to the builds shelf at `{builds_registry}/images-digests/all:run-{N}` via the existing `push_build`.
- **Drop** `--lock-project` (convention replaces it: always `images-digests/all`). **Keep** `--builds-registry` + `--run-number`, now driving the digest push instead of the lock push.
- Do **not** push `workloads/images.lock` to the shelf (in source control; sole consumer was the stapler being removed).

## Consumer workflows

- **Image repos** (capture-tool, later): build jobs wire `--builds-registry` + `--run-number` on the `uv run build --mode ci` invocation. Today capture-tool passes none → nothing is pushed.
- **placeframe** (now): prerelease job gains `contents: write` (currently `contents: read` — latent; today's verb never creates a draft because no apps, but the new append logic will need it).

## release-devkit

### Config

No new section. The digest-manifest pull reuses `apps[].builds.registry` for the shelf root + the conventional `images-digests/all` project/platform. Repos without images simply have no manifest on the shelf — the pull is best-effort (skip if absent), so no image rows render.

### `create-release` (stable, runs inside `release`)

After the existing packages table + app versions + app asset pull, also pull the digest manifest from the matched integrate run's shelf and render a **Built images** table on the release body: `target | [tree-tag](ghcr-package-url) | sha256:…`. Body-only, no asset file. Stable body is computed fresh from tags + manifest; the dev-pile is deleted on promotion (unchanged, `release.py:91`).

### `prerelease` (dev draft)

Replace the current `if has_app_changes:` gate (`prerelease.py:123`) with an always-on tail. Compute this run's delta per kind — packages (existing plan path-diff), apps (existing source path-diff), images (content-based: digest not already in the pile). If the delta is empty across all kinds → touch nothing (no draft creation, no section; today's "Nothing to publish" exit stands). If non-empty → append one per-run section to the `dev-builds` draft containing **only the changed kinds' rows**. Packages: dev version + registry link. Apps: asset download links. Images: tree-tag + digest.

### `update-pr-draft-release` (PR draft)

Gains digest-manifest pull from the **current** integrate run's shelf (`run-{N}` = ambient run number, no matched-run lookup) + body rendering. Today pr-{N} drafts have an empty body (`--notes ''`) and just asset uploads; under this they get a per-run section with the image-digest table + asset links. PR drafts show app assets + image digests only (no package rows — nothing publishes on a PR). Merge-gate's pr-{N} deletion stays unchanged.

### Shared append helper (new, in `draft_releases.py`)

`append_draft_section(tag, repo, section, anchor)` — ensure draft → read body via `gh release view --json body` → **idempotent replace-or-append** keyed by `<a id="run-N"></a>` HTML anchor (release bodies get no auto heading anchors — verified; inline HTML anchors work) → write via `gh release edit --notes-file`. Newest-first (new section prepended). Used by both `prerelease` (dev-builds) and `update-pr-draft-release` (pr-{N}).

### lint-workflows

Grow a **permissions-block validator** — assert the documented per-verb `permissions:` contract (today zero permission checking exists; placeframe's `contents: read` on prerelease passes lint despite the doc saying `contents: write`). Covers all draft-creating verbs: `prerelease`, `release`, `update-pr-draft-release`.

## The three surfaces

| Surface | Stage | Shows |
|---|---|---|
| Stable release (`YYYY.MM.N`) | main push | packages (stable versions) + app versions + app assets + built-image digests |
| Dev draft (`dev-builds`) | dev push | per-run sections, only changed kinds: packages (dev versions) + changed app assets + changed image digests |
| PR draft (`pr-{N}`) | integrate (PR) | per-run sections: app assets + image digests (no packages — nothing publishes) |

## Section mechanics (shared)

- Each section: `<a id="run-{N}"></a>` + heading with links to the release/integrate run + PR (PR link from the merge-message convention "Merge PR #N: title").
- Reverse link: the writing run's `$GITHUB_STEP_SUMMARY` links to the draft's `untagged-<hash>` URL `#run-{N}` (draft tag-URLs 404 — verified; `untagged-<hash>` from `gh release view --json url`).
- Re-run safety: replace-by-`run-{N}` anchor (same run number → overwrite, not duplicate).
- Concurrency safety: `release.yml`'s `release-${{ github.ref }}` no-cancel queue serializes dev prerelease runs; pr-{N} writes are per-PR (no cross-PR contention).

## Implementation order

1. **placeframe first**: `contents: write` on prerelease + the package-only dev-draft append path (no apps, no images). End-to-end test of the append machinery, idempotent sections, summary backlink.
2. **docker-devkit**: digest-manifest recording + push (the one-time shared change).
3. **capture-tool**: wire build-zed flags + full image-digest rendering on all three surfaces (the fullest test).
4. **lint**: permissions-block validator (can land any time; placeframe's compliance surfaces it).

## Spec details (non-blocking, for impl reference)

- Digest manifest JSON schema: `target → {ref, digest, tags[]}`
- Matched-integrate-run `html_url`: add to the existing jq in `matched_ci_run_number` (currently extracts only `run_number`)
- PR-link derivation: parse "Merge PR #N: title" from the merge message (fall back to `gh api /commits/{sha}/pulls` if needed)
- Whether to run the matched-run lookup when no assets (package-only case like placeframe): run it for the integrate-run link in the section, or skip — cheap either way
- Best-effort digest-manifest pull: `bash_check` for shelf existence before `pull_build` (repos without images naturally skip)
- `dry_run` already guards the whole path (`prerelease.py:76`) — confirm new append logic sits after it
- Multi-variant repos (cuda/rocm matrix → separate runs): known limitation, defer until one exists
- ghcr package-page URL shape (verified): `https://github.com/orgs/{owner}/packages/container/{repo}%2F{image}`

## Open verification (non-blocking)

- Deploy tooling (`install-zed`) pulls by tree-tag (`compose.rig.yml:3` confirms `${ZED_CAPTURE_SHA}`) — digest/tree-tag handles on release pages are load-bearing. Verify no deploy path pulls `:latest` (separate from this work).

## Verified platform facts

- Draft release `html_url` is `/releases/tag/untagged-<hash>` (tag-URLs 404 for drafts; gh cli#11589). `gh release view/edit/upload <tag>` still resolve drafts — the org's `ensure_draft_release`/`delete_draft_release` already rely on that.
- Release bodies get no auto heading anchors (unlike READMEs). Inline `<a id="…"></a>` HTML anchors render and `#anchor` fragments on the release URL scroll to them (proven by the `ghalactic/github-release-from-tag` action).
- Asset download URLs for drafts work (already load-bearing in this org's pr-draft design).
- `release.yml`'s `concurrency: release-${{ github.ref }}` with no-cancel serializes dev prerelease runs 1:1 → read-modify-write append is safe. The residual main-vs-dev race (promotion deletes draft while dev run appends) exists today for asset uploads too; different refs, different concurrency groups, unchanged.
- ghcr package page (verified against `outernet-foundation/placeframe-capture-tool/zed-capture`): `https://github.com/orgs/{owner}/packages/container/{repo}%2F{image}`. Per-version pages use a numeric ID (API-resolvable); package-root is the clean link target.
- Built-image pull handle is the tree-tag, not `:latest`. `compose.rig.yml:3` pulls `ghcr.io/.../zed-capture:${ZED_CAPTURE_SHA}` where `ZED_CAPTURE_SHA` = tree-sha from `compute_service_shas`. `:latest` is pushed but never referenced — don't show it on pages.
