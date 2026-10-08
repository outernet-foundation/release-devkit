# Fix plan — dev version keying: short SHA → repo commit count

The dev channel's prerelease versions are invalid on PyPI and must switch from the 12-hex short-SHA key to `git rev-list --count HEAD`, across every registry. Designed and agreed; not yet implemented.

## The failure

`pep440_dev_version` spells `{base}.dev{short_sha}` (e.g. `0.2.1.dev15630505b8c2`). PEP 440's `.dev` segment must be numeric, so `uv build` rejects the ephemeral patch before anything reaches PyPI — docker-devkit's dev Release fails at publish. The SHA-preserving alternative, `0.2.1.dev0+15630505b8c2`, is valid PEP 440 but PyPI rejects `+local` versions on upload. There is no way to keep the hex SHA in a PyPI dev version.

## The decision

- Key every registry's dev version on the repo-wide commit count: `git rev-list --count HEAD`, computed once per run in `publish_packages` and passed down. No short SHA in any version spelling, on any registry.
- Grammar stays per registry: `{base}.dev{count}` on PyPI, `{base}-dev.{count}` on npm and nuget (numeric prerelease identifiers are valid semver).
- The short SHA survives where it is structural, not a version: `dev-builds` section anchors (`sha-{short}`), heading links, and draft asset names (`{stem}-{short}.{ext}`).

## Why the count is sound

- PEP 440-legal and acceptable to PyPI (numeric, no local segment).
- Re-run idempotent: the same SHA re-derives the same count, so `uv publish --check-url` and npm's EPUBLISHCONFLICT swallow re-runs instead of minting a new version per run (a run-ID key would not).
- Monotone per package: a package only publishes when its own path diffs against its last tag, which implies at least one new commit, which moves the repo count. Later dev prereleases always sort after earlier ones.
- An event ordinal: every package published from one merge carries the same number across registries, and co-publishing sibling dependency pins read as same-event.
- Invertible with the repo: the count is an index into `git rev-list --reverse HEAD` — the Nth commit is the SHA.

Accepted edge: rewriting dev history shifts counts; if a shifted count collides with an already-published `(base, count)`, the publish degrades to an idempotent skip, not corruption. Dev is append-only in the bors model (main fast-forwards it), so this only bites on operator-driven rewrites.

## Implementation

- `publishing.py`: `dev_version(base_version, commit_count)` on the `Registry` protocol and all three adapters; `pep440_dev_version(base, count)`; `semver_dev_version(base, count)`; `resolve_publish_versions` drops `short_sha` and spells co-publishing siblings with the same count (no `ResolvedDependency` change, no per-path plumbing).
- `verbs/release.py`: `publish_packages` computes `commit_count` once (`git rev-list --count HEAD`) and passes it in place of `short_sha`; the spine's `short_sha` remains for anchors, headings, and asset names.
- `tests/test_prerelease.py`: the two `-dev.{SHORT_SHA}` assertions; add coverage for the PyPI spelling and the sibling spelling.
- `AGENTS.md` "Dev channel": rewrite the spelling sentence (currently specifies `{base}.dev{short}` on PyPI) to the count grammar with the numeric-rationale and the accepted rewrite edge.
- Not changing: `get-app-version` keeps its path-scoped count (Android per-app monotonic `bundleVersionCode` — a different law); the path-diff blind spot is a separate bug (`CRITICAL-BUG.md`).

## Landing sequence

1. Commit the above to release-devkit `dev` and push (local dev already carries the unpushed pr-draft lint requirement, the AGENTS prose, and `CRITICAL-BUG.md`).
2. Bump the wrapper pin (`RELEASE_DEVKIT_COMMIT`) in every consumer to the new dev tip — unity-devkit and docker-devkit carry unlanded local commits for that re-pin wave (each branch tip adds the `update-pr-draft-release` job; their lint will demand it at the new pin). The consumer sweep (7 repos) picks up the same pin plus the config/verb migration.
3. Re-run the failed dev Release workflows: unity-devkit also needs the prerelease permissions fix (landed on its `prerelease-permissions` branch — `contents: write` to create the `dev-builds` draft); docker-devkit's permissions block is already correct.
