from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp

from bashrun.bash import bash, bash_check, bash_output
from ci_devkit.builds import pull_build

from release_devkit.context import VerbContext
from release_devkit.plan import UNCHANGED_FALLBACK_VERSION
from release_devkit.publishing import build_registries
from release_devkit.tags import latest_version

DEV_DRAFT_TAG = "dev-builds"


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [f"| {' | '.join(headers)} |", f"|{'|'.join('---' for _ in headers)}|"]
    lines.extend(f"| {' | '.join(row)} |" for row in rows)
    return "\n".join(lines)


def write_release(
    context: VerbContext,
    tag: str,
    versions: dict[str, str | None],
    heading: str | None,
    published: list[tuple[str, str]] | None,
    publish: bool,
) -> None:
    repository = context.settings.github_repository

    # Ensure a draft release exists and read its current body
    view_command = f"gh release view {tag} --repo {repository}"
    body = ""
    if bash_check(view_command):
        body = json.loads(bash_output(f"{view_command} --json body"))["body"]
    else:
        bash(f"gh release create {tag} --draft --target {context.head} --title {tag} --notes '' --repo {repository}")

    # Stage every app's build artifacts as release assets
    staged: list[tuple[str, str, Path]] = []
    apps_with_builds = {name: app.builds for name, app in context.publish_config.apps.items() if app.builds}
    if apps_with_builds:
        staging = Path(mkdtemp(prefix="release-builds-"))
        for app_name, artifact in [
            (app_name, artifact) for app_name, artifacts in apps_with_builds.items() for artifact in artifacts
        ]:
            layer = staging / f"{artifact.project}-{artifact.platform}"
            pull_build(
                context.publish_config.builds_registry or "",
                artifact.project,
                artifact.platform,
                f"sha-{context.certified}",
                layer,
                registry_username=context.settings.github_actor,
                registry_token=context.settings.github_token,
            )

            # Select the file inside the pulled layer that becomes the asset
            files = sorted(path for path in layer.rglob("*") if path.is_file())
            if artifact.file is not None:
                source = next((path for path in files if path.name == artifact.file), None)
                if source is None:
                    raise SystemExit(f"Build artifact layer '{artifact.file}' not found under {layer}")
            elif len(files) == 1:
                source = files[0]
            else:
                raise SystemExit(
                    f"Build artifact for ({artifact.project}, {artifact.platform}) pulled multiple files "
                    f"({', '.join(path.name for path in files)}); declare which one with 'file'"
                )

            # Copy the asset under its release name and record it
            named = Path(artifact.name) if artifact.name else source
            name = named.name if publish else f"{named.stem}-{context.short}{named.suffix}"
            target = staging / name
            shutil.copy2(source, target)
            staged.append((app_name, name, target))
            print(f"  Asset: {name}")

    # Upload the staged assets
    if staged:
        bash(f"gh release upload {tag} {' '.join(f'"{path}"' for _, _, path in staged)} --clobber --repo {repository}")

    # Assemble the notes section from the heading and the artifact tables
    prefix = "#" * (2 if publish else 4)
    blocks: list[str] = []
    if heading is not None:
        blocks.append(heading)

    # List published packages with their registry links
    if published is not None:
        configured = context.publish_config.packages
        table_rows: list[list[str]] = []
        for name, package in configured.items():
            version = (
                next(
                    (
                        published_version
                        for identity, published_version in reversed(published)
                        if identity in package.registries.values()
                    ),
                    None,
                )
                or latest_version(f"{name}-v")
                or UNCHANGED_FALLBACK_VERSION
            )
            registry_cells = [
                f"[{registry_name}]({build_registries('')[registry_name].url(identity, version)})"
                if version != UNCHANGED_FALLBACK_VERSION
                else registry_name
                for registry_name, identity in package.registries.items()
            ]
            table_rows.append([name, version, ", ".join(registry_cells) or "—"])
        if table_rows:
            blocks.append(f"{prefix} Packages\n{markdown_table(['Package', 'Version', 'Registry'], table_rows)}")

    # List staged apps with their asset links
    if staged:
        table_rows = [
            [
                app_name,
                versions.get(app_name) or "—",
                f"[{asset_name}](https://github.com/{repository}/releases/download/{tag}/{asset_name})",
            ]
            for app_name, asset_name, _ in staged
        ]
        blocks.append(f"{prefix} Apps\n{markdown_table(['App', 'Version', 'Asset'], table_rows)}")

    # List built images from the digest manifest
    if context.manifest:
        table_rows = []
        for image_name, entry in context.manifest.items():
            tree_tag = next(
                (tag_name for tag_name in entry.tags if tag_name.startswith("tree-")),
                entry.tags[0] if entry.tags else "",
            )
            url = (
                f"https://github.com/orgs/{ref_parts[0]}/packages/container/{ref_parts[1].replace('/', '%2F')}"
                if entry.ref.startswith("ghcr.io/")
                and len(ref_parts := entry.ref[len("ghcr.io/") :].split("/", 1)) >= 2
                else None
            )
            table_rows.append([
                image_name,
                f"[{tree_tag}]({url})" if url is not None and tree_tag else (tree_tag or "—"),
                f"`{entry.digest}`",
            ])
        blocks.append(f"{prefix} Built images\n{markdown_table(['Image', 'Tag', 'Digest'], table_rows)}")

    # Join the blocks into one section
    section = "\n\n".join(blocks)

    # Splice the section into the draft body at its SHA anchor
    if not publish:
        anchor = f"sha-{context.short}"
        parts = re.split(r'<a id="([^"]+)"></a>', body)
        sections = {parts[index]: parts[index + 1].strip() for index in range(1, len(parts), 2)}
        sections.pop(anchor, None)
        sections = {anchor: section, **sections}
        section = "\n\n".join(f'<a id="{anchor_id}"></a>\n{content}' for anchor_id, content in sections.items())

    # Apply the notes to the release from a temp file
    with NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as file:
        file.write(section + "\n")
        notes_path = file.name
    try:
        bash(
            f"gh release edit {tag}{' --draft=false' if publish else ''} --repo {repository} --notes-file {notes_path}"
        )
    finally:
        Path(notes_path).unlink()


def delete_draft_release(tag: str, repository: str) -> None:
    if not bash_check(f"gh release view {tag} --repo {repository}"):
        return
    bash(f"gh release delete {tag} --cleanup-tag --yes --repo {repository}")
