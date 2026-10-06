# Plan: full release surfaces (packages, apps, image digests)

Locked plan. Every release surface — stable releases, the `dev-builds` dev draft, and `pr-{N}` PR drafts — includes everything produced at its stage: packages (with versions/registry links), app build assets (with download links), and built-image digests (tree-tag + digest). Base/mirror image pins do not appear on any page — they're in source control (`workloads/images.lock`).

## docker-devkit (done, step 2)

- In CI mode, distill bake's `--metadata-file` into a digest manifest — structured JSON: `target → {ref, digest, tags[]}` — and push it to the builds shelf at `{builds_registry}/images-digests/all:run-{N}` via the existing `push_build` (file name `images-digests.json`).
- **Drop** `--lock-project` (convention replaces it: always `images-digests/all`). **Keep** `--builds-registry` + `--run-number`, now driving the digest push instead of the lock push.
- Do **not** push `workloads/images.lock` to the shelf (in source control; sole consumer was the stapler being removed).

## Consumer workflows

- **Image repos** (capture-tool, done, step 3): build jobs wire `--builds-registry` (value = the `apps[].builds.registry` shelf root, e.g. `ghcr.io/{owner}/{repo}/builds`) + `--run-number ${{ github.run_number }}` on the `uv run build --mode ci` invocation. The `--builds-registry` value must match `apps[].builds.registry` so the manifest pull resolves. capture-tool `build-zed` now passes both (folded `>-` over 120 chars); `setup-release-devkit` wrapper repinned to the step-3 release-devkit commit `ed406a0`. Branch `update-release-devkit`. The push itself needs docker-devkit released to PyPI (step 2 on `dev`, unreleased) before it produces a manifest.
- **placeframe** (done, step 1): prerelease permissions changed to `contents: write` + `packages: read` + `actions: read`; release-devkit pin bumped to `791f033`. Branch `more-ci-fixes`.

## release-devkit

### Config

No new section. The digest-manifest pull reuses `apps[].builds.registry` (`BuildsConfig.registry` in `config.py`) for the shelf root + the conventional `images-digests/all` project/platform. release-devkit cannot import docker-devkit (sibling packages, no dep edge), so the convention constants (`images-digests`, `all`, `images-digests.json`) are duplicated as string literals here — a convention, not a shared import. Repos without images simply have no manifest on the shelf — the pull is best-effort (use ci-devkit's `build_exists` before `pull_build`; repos without images naturally skip), so no image rows render. If no app declares `builds`, there's no shelf root → skip the pull entirely.

### `create-release` (stable, runs inside `release`, done step 3)

After the existing packages table + app versions + app asset pull (`collect_build_assets`, `create_release.py:84`), also pull the digest manifest from the matched integrate run's shelf and render a **Built images** table on the release body: `target | [tree-tag](ghcr-package-url) | sha256:…`. Body-only, no asset file. Append the table to the `lines` list in `run_create_release` (`create_release.py:45-67`) before the `gh release create` call. Stable body is computed fresh from tags + manifest; the dev-pile is deleted on promotion (unchanged, `release.py:91`).

### `prerelease` (dev draft, done step 3)

The always-on tail landed in step 1 (`prerelease.py:63-141`): computes package + app deltas, appends a per-run section via `build_prerelease_section` (`prerelease.py:158`). Step 3 adds the **images** kind: pull this run's manifest from the matched integrate run's shelf (`matched_ci_run_number`), compute a content-based delta (digest not already in the `dev-builds` body — regex `sha256:[a-f0-9]{64}` over the existing body), and append image rows (tree-tag + digest) to `build_prerelease_section`'s output only for digests not already in the pile. The "Nothing to publish" exit (`prerelease.py:77`) now also considers whether any image digest is new.

### `update-pr-draft-release` (PR draft, done step 3)

`update_pr_draft` (`draft_releases.py:33`) gains a digest-manifest pull from the **current** integrate run's shelf (`--run-number` = ambient run number, no matched-run lookup) + a per-run body section via `append_draft_section` (the helper landed in step 1 but this verb doesn't use it yet). Today pr-{N} drafts have an empty body (`--notes ''` at `draft_releases.py:77`) and just asset uploads + `emit_draft_summary`; under this they get a per-run section with the image-digest table + asset links. PR drafts show app assets + image digests only (no package rows — nothing publishes on a PR). Merge-gate's pr-{N} deletion stays unchanged.

### Shared append helper (done, step 1, in `draft_releases.py`)

`append_draft_section(tag, repository, sha, anchor, section)` — ensure draft → read body via `gh release view --json body` → **idempotent replace-or-append** keyed by `<a id="run-N"></a>` HTML anchor → write via `gh release edit --notes-file`. Newest-first (new section prepended). Already used by `prerelease` (dev-builds); step 3 wires it into `update-pr-draft-release` (pr-{N}) — today that verb uploads assets + `emit_draft_summary` only, no body section (`draft_releases.py:33`).

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

1. **placeframe** (done): `contents: write` on prerelease + the package-only dev-draft append path. release-devkit commits `3128a22` (code) + `791f033` (prose) on `dev`, pushed. placeframe branch `more-ci-fixes`, commit `3782432b`, pushed. Landed: `append_draft_section` + `replace_or_prepend_section` + `emit_draft_backlink` (`draft_releases.py`); always-on prerelease tail with `parse_merge_pr` + `build_prerelease_section` (`prerelease.py`); shared `registry_url` (`registries.py`, `create_release.py` refactored to use it). 228 tests pass, ruff + basedpyright clean.
2. **docker-devkit** (done): digest-manifest recording + push (the one-time shared change). docker-devkit commits `9ab7c09` (code) + `975baf0` (prose) on `dev`. Landed: `distill_digest_manifest` + `push_image_digests` (`build_docker.py`); `--lock-project` + `lock_project` + `push_images_lock` + `IMAGES_LOCK_PLATFORM` dropped; digest manifest (`target → {ref, digest, tags[]}`) written to a `images-digests.json` temp file and pushed to `images-digests/all` via `push_build`; `workloads/images.lock` no longer pushed to the shelf. Tests in `test_build_docker.py` (7 new). 147 tests pass, ruff + basedpyright clean.
3. **capture-tool + release-devkit** (done): wire `--builds-registry` + `--run-number` on `uv run build --mode ci` (capture-tool `integrate.yml`) + full image-digest rendering on all three surfaces (release-devkit). release-devkit commit `ed406a0` (code) on `dev`. Landed: shared `pull_digest_manifest(builds_registry, run_number, actor, token)` (best-effort via `build_exists` before `pull_build`) + `render_images_table(manifest)` + `ghcr_package_url(ref)` + `pick_tree_tag(tags)` + `builds_registry_of(publish_config)` + `DigestEntry`/`MatchedRun` pydantic models (`create_release.py`); `matched_ci_run_number` now returns `(run_number, html_url)` (jq object `{run_number, html_url}`); "Built images" table appended to `run_create_release`'s `lines` before `gh release create`; image-digest rows in `prerelease` sections via `build_prerelease_section` (content-based delta: regex `sha256:[a-f0-9]{64}` over the existing `dev-builds` body via `existing_dev_builds_digests`, only new digests; "Nothing to publish" now also considers `has_image_changes`); per-run section in `update-pr-draft-release` via `append_draft_section` + `build_draft_section` (`draft_releases.py`, ambient `--run-number`, no matched-run lookup). `collect_build_assets` returns `(assets, run_number)` so the stable manifest pull reuses the single matched-run lookup. capture-tool commit `fdff94a` (code) + `5f4726b` (prose) on `update-release-devkit`: `build-zed` folds `uv run build` over 120 chars with `--builds-registry ghcr.io/outernet-foundation/placeframe-capture-tool/builds` + `--run-number ${{ github.run_number }}`; wrapper repinned to `ed406a0`. 246 tests pass, ruff + basedpyright clean. Dependency: capture-tool's manifest push needs docker-devkit released to PyPI (step 2 on `dev`, unreleased); the release-devkit pin (`ed406a0`) must be pushed to remote before capture-tool CI runs (the `git clone` in the wrapper resolves the SHA from origin).
4. **lint**: permissions-block validator (can land any time; placeframe's compliance surfaces it). Assert the documented per-verb `permissions:` contract for `prerelease` (`contents: write` + `packages: read` + `actions: read` + `id-token: write`), `release`, `update-pr-draft-release`.

## Spec details (non-blocking, for impl reference)

- Digest manifest JSON schema: `target → {ref, digest, tags[]}`. Buildx `--metadata-file` flat keys per target: `image.name` (comma-separated pushed refs `registry/repo:tag[,registry/repo:tag2]`, present only with `--push`) + `containerimage.digest` (`sha256:…`; the manifest-list digest for multi-platform). Distill: split `image.name` by comma, strip `@digest`, `rpartition(":")` for repo + tag.
- Convention constants (duplicated in release-devkit, not imported from docker-devkit — siblings, no dep edge): project `images-digests`, platform `all`, file `images-digests.json`. Shelf ref via `build_reference(registry, "images-digests", "all", f"run-{N}")`.
- Best-effort digest-manifest pull: `build_exists` (ci-devkit `builds.py`) before `pull_build` — ORAS knowledge lives in ci-devkit, not raw `bash_check`. Pass `registry_username`/`registry_token` through (same as `pull_build_assets`).
- Matched-integrate-run `html_url`: extend the jq in `matched_ci_run_number` (`create_release.py:97`, currently `.workflow_runs[0].run_number`) to return `{run_number, html_url}`; return both. Callers: `collect_build_assets` (`create_release.py:85`) + `prerelease.py:131`. The `html_url` feeds the section heading (replaces the step-1 current-run URL `https://github.com/{repo}/actions/runs/{run_id}`). The anchor stays `run-{dev_run_id}` (idempotency for the writing dev-push run, NOT the integrate run).
- "Matched-run lookup for no assets" (step 1 decided: skip lookup, use current-run URL): SUPERSEDED by step 3 — the manifest pull always needs the matched run number, so the lookup always runs when images exist; the `html_url` from it feeds the heading. When a repo has neither apps nor images, the lookup is still skipped (no shelf to pull from).
- Content-based delta (prerelease only): the `dev-builds` draft accumulates sections; a re-built image with an unchanged digest must not re-surface. Pull the current run's manifest, extract digests already in the body (regex `sha256:[a-f0-9]{64}`), render only rows whose digest is new. Stable release + PR draft show the full manifest (no delta — each is per-run, not accumulating).
- `dry_run` guard (confirmed, step 1): the append logic sits after the `dry_run` early return at `prerelease.py:81`.
- Multi-variant repos (cuda/rocm matrix → separate runs): known limitation, defer until one exists.
- ghcr package-page URL shape (verified): `https://github.com/orgs/{owner}/packages/container/{repo}%2F{image}` — strip `ghcr.io/` prefix, first segment = owner, rest with `/` → `%2F`.

## Open verification (non-blocking)

- Deploy tooling (`install-zed`) pulls by tree-tag (`compose.rig.yml:3` confirms `${ZED_CAPTURE_SHA}`) — digest/tree-tag handles on release pages are load-bearing. Verify no deploy path pulls `:latest` (separate from this work).

## Verified platform facts

- Draft release `html_url` is `/releases/tag/untagged-<hash>` (tag-URLs 404 for drafts; gh cli#11589). `gh release view/edit/upload <tag>` still resolve drafts — the org's `ensure_draft_release`/`delete_draft_release` already rely on that.
- Release bodies get no auto heading anchors (unlike READMEs). Inline `<a id="…"></a>` HTML anchors render and `#anchor` fragments on the release URL scroll to them (proven by the `ghalactic/github-release-from-tag` action).
- Asset download URLs for drafts work (already load-bearing in this org's pr-draft design).
- `release.yml`'s `concurrency: release-${{ github.ref }}` with no-cancel serializes dev prerelease runs 1:1 → read-modify-write append is safe. The residual main-vs-dev race (promotion deletes draft while dev run appends) exists today for asset uploads too; different refs, different concurrency groups, unchanged.
- ghcr package page (verified against `outernet-foundation/placeframe-capture-tool/zed-capture`): `https://github.com/orgs/{owner}/packages/container/{repo}%2F{image}`. Per-version pages use a numeric ID (API-resolvable); package-root is the clean link target.
- Built-image pull handle is the tree-tag, not `:latest`. `compose.rig.yml:3` pulls `ghcr.io/.../zed-capture:${ZED_CAPTURE_SHA}` where `ZED_CAPTURE_SHA` = tree-sha from `compute_service_shas`. `:latest` is pushed but never referenced — don't show it on pages.
