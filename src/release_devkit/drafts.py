from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp

from bashrun.bash import bash, bash_check, bash_output

from release_devkit.builds import pull_build_assets
from release_devkit.context import VerbContext
from release_devkit.plan import package_rows
from release_devkit.rendering import markdown_table, render_images_table

DEV_DRAFT_TAG = "dev-builds"


def write_release(
    context: VerbContext,
    tag: str,
    versions: dict[str, str | None],
    heading: str | None,
    published: list[tuple[str, str]] | None,
    publish: bool,
) -> None:
    repository = context.settings.github_repository

    view_command = f"gh release view {tag} --repo {repository}"
    body = ""
    if bash_check(view_command):
        body = json.loads(bash_output(f"{view_command} --json body"))["body"]
    else:
        bash(f"gh release create {tag} --draft --target {context.head} --title {tag} --notes '' --repo {repository}")

    staged: list[tuple[str, str, Path]] = []
    if context.publish_config.apps:
        short = None if publish else context.short
        staging = Path(mkdtemp(prefix="build-assets-"))
        for app_name, artifact, source in pull_build_assets(
            context.publish_config.apps,
            context.publish_config.builds_registry,
            context.certified,
            context.settings.github_actor,
            context.settings.github_token,
        ):
            named = Path(artifact.name) if artifact.name else source
            name = f"{named.stem}-{short}{named.suffix}" if short is not None else named.name
            target = staging / name
            shutil.copy2(source, target)
            staged.append((app_name, name, target))
            print(f"  Asset: {name}")

    if staged:
        bash(f"gh release upload {tag} {' '.join(f'"{path}"' for _, _, path in staged)} --clobber --repo {repository}")

    prefix = "#" * (2 if publish else 4)
    blocks: list[str] = []

    if heading is not None:
        blocks.append(heading)

    if published is not None:
        configured = context.publish_config.packages
        names_by_identity = {
            identity: name for name, package in configured.items() for identity in package.registries.values()
        }
        overrides = {names_by_identity[identity]: version for identity, version in published}
        table_rows: list[list[str]] = []
        for package_row in package_rows(configured, overrides):
            if not package_row.registries:
                table_rows.append([package_row.name, package_row.version, "—"])
                continue
            registry_versions = {link.version for link in package_row.registries}
            if len(registry_versions) == 1:
                version_cell = next(iter(registry_versions))
            else:
                version_cell = ", ".join(f"{link.version} ({link.name})" for link in package_row.registries)
            registries_cell = ", ".join(
                f"[{link.name}]({link.url})" if link.url is not None else link.name for link in package_row.registries
            )
            table_rows.append([package_row.name, version_cell, registries_cell])
        if table_rows:
            blocks.append(f"{prefix} Packages\n{markdown_table(['Package', 'Version', 'Registry'], table_rows)}")

    if staged:
        table_rows = []
        for app_name, asset_name, _ in staged:
            version = versions.get(app_name)
            version_cell = version if version is not None else "—"
            asset_url = f"https://github.com/{repository}/releases/download/{tag}/{asset_name}"
            table_rows.append([app_name, version_cell, f"[{asset_name}]({asset_url})"])
        blocks.append(f"{prefix} Apps\n{markdown_table(['App', 'Version', 'Asset'], table_rows)}")

    if context.manifest:
        blocks.append(f"{prefix} Built images\n{render_images_table(context.manifest)}")

    section = "\n\n".join(blocks)

    if not publish:
        anchor = f"sha-{context.short}"
        parts = re.split(r'<a id="([^"]+)"></a>', body)
        sections = {parts[index]: parts[index + 1].strip() for index in range(1, len(parts), 2)}
        if anchor in sections:
            sections[anchor] = section
        else:
            sections = {anchor: section, **sections}
        section = "\n\n".join(f'<a id="{anchor_id}"></a>\n{content}' for anchor_id, content in sections.items())

    draft_flag = " --draft=false" if publish else ""
    with NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as file:
        file.write(section + "\n")
        notes_path = file.name
    try:
        bash(f"gh release edit {tag}{draft_flag} --repo {repository} --notes-file {notes_path}")
    finally:
        Path(notes_path).unlink()


def delete_draft_release(tag: str, repository: str) -> None:
    if not bash_check(f"gh release view {tag} --repo {repository}"):
        return
    bash(f"gh release delete {tag} --cleanup-tag --yes --repo {repository}")
