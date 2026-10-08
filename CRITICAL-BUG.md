# CRITICAL BUG — path-diff change detection cannot see build inputs outside a package's declared path

**The detector gap is UNFIXED — nothing at plan, lint, or publish time can catch such a reference. A workspace audit found no live instance (see "Audit"), so current "unchanged" verdicts rest on the packages' present hermeticity, not on the detector; a reference introduced after the audit ships stale with zero signal.**

## The bug

Change detection is `git diff <last-tag> HEAD -- <package.path>` — a path diff over the package's configured `path`, nothing else (`tags.py`, `changed_since_tag`). A package whose **build consumes files outside its declared path** (a build step that copies, compiles, or embeds from a sibling directory or anywhere else in the repo — a true bits-inclusion path reference) does not republish when those inputs change. The artifact ships stale bits with zero signal: no error, no warning, and nothing at plan time, lint time, or publish time that can detect the misconfiguration. Such a reference can be introduced at any time and nothing will catch it.

## What this is not

- Specifier references — UPM `package.json` dependencies, npm `dependencies`, pypi `[tool.uv.sources]` overrides, nuget `PackageReference` — do not embed sibling bits. When a sibling changes and the dependent's own path does not, the dependent's shipped artifact is byte-identical to its last publish and its dependency floors are exact. That is the no-cascade law (see "The CI-commit-free invariants" in `AGENTS.md`) — a designed trade, not this bug.
- A Unity *project* consuming a package by `file:` path is covered when that project is an app: apps re-staple unconditionally whenever any package publishes.

This bug is exclusively: **package artifact content depends on files outside the package's configured `path`.**

## The failure mode

1. Package B's build reads files from outside `B.path` — a sibling directory, repo-root assets, anything.
2. Those files change; B's own path does not.
3. Plan core verdict: B unchanged → not published (stable), not prereleased (dev).
4. Consumers keep installing B's stale artifact. Nothing fails, anywhere, ever.

## Audit (no live instances)

Every consumer config in the workspace was swept for package builds consuming files outside their declared `path`. Zero instances found:

- **`path: .` repos** (bashrun, ci-devkit, python-devkit, docker-devkit, logger-conf, openapi-client-codegen, pydantic-settings-pulumi) — the path is the whole repo; the blind spot is structurally empty.
- **npm packages** (Nessle, ObserveThing, extruded-text, lbe-toolkit ×3, playerbuild, placeframe's six UPM packages, placeframe-api-client's npm side) — no `package.json` carries `scripts`, so no `prepack`/`prepare` can pull bits in; `npm publish` packs only in-dir content.
- **PyPI sub-path packages** (placeframe-common, placeframe-core-python, unity-devkit) — hatch wheel builds scoped to in-path `src/<pkg>`; no force-includes outside.
- **NuGet** (placeframe-api-client, the one `dotnet pack`) — the csproj declares no imports, outside globs, or ProjectReferences; the only `Directory.Build.props` on the tree sits inside the package path (shielding MSBuild's ancestor walk); the repo's lone `NuGet.config` is not an ancestor of the path; PackageReferences are exact-pinned registry deps (a specifier reference, not this bug).
- **Cross-cutting** — no symlinks inside any package path, no copy/rsync steps in any release workflow, and the `bin/`/`obj/` directories beside the csproj are untracked build outputs, not inputs.
- **The generated api-client's upstream sources are covered by commitment**: codegen output is committed inside its path, so regeneration always trips the path-diff, and the `generate-clients --check` staleness gate forces regeneration in CI.

The audit is a snapshot: it verifies the escape hatches are unused today, not that they are unusable. Any of the following reintroduces the risk silently — an npm `prepack` script, a hatch force-include outside the path, a csproj `Import`/glob/ProjectReference above the path, a `Directory.Build.props` or `NuGet.config` appearing at an ancestor, a workflow copy step before publish.

## Fix directions (unsettled)

- Require every package's build inputs to be declared and covered by its configured `path`, validated at plan time; or
- re-run the sweep above (cheap, but buys only a snapshot — it rots the day after); or
- make package builds hermetic to the package path so the blind spot is structurally impossible.
