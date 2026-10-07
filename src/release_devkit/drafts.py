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
from release_devkit.rendering import render_images_table

DEV_DRAFT_TAG = "dev-builds"


def write_release(
    context: VerbContext,
    tag: str,
    short: str | None,
    versions: dict[str, str | None],
    heading: str | None,
    published: list[tuple[str, str, str]] | None,
    publish: bool,
) -> None:
    repository = context.settings.github_repository

    body = ""
    if not bash_check(f"gh release view {tag} --repo {repository}"):
        bash(f"gh release create {tag} --draft --target {context.head} --title {tag} --notes '' --repo {repository}")
    else:
        body = json.loads(bash_output(f"gh release view {tag} --repo {repository} --json body"))["body"]

    staged: list[tuple[str, str, Path]] = []
    if context.publish_config.apps:
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
    blocks: list[list[str]] = []

    if heading is not None:
        blocks.append([heading])

    if published is not None:
        configured = context.publish_config.packages
        names_by_identity = {
            identity: name for name, package in configured.items() for identity in package.registries.values()
        }
        overrides = {names_by_identity[identity]: version for _, identity, version in published}
        rows = package_rows(configured, overrides)
        if rows:
            package_lines = ["| Package | Version | Registry |", "|---|---|---|"]
            for row in rows:
                if not row.registries:
                    package_lines.append(f"| {row.name} | {row.version} | — |")
                    continue
                registry_versions = {link.version for link in row.registries}
                if len(registry_versions) == 1:
                    version_cell = next(iter(registry_versions))
                else:
                    version_cell = ", ".join(f"{link.version} ({link.name})" for link in row.registries)
                registry_parts: list[str] = []
                for link in row.registries:
                    if link.url is not None:
                        registry_parts.append(f"[{link.name}]({link.url})")
                    else:
                        registry_parts.append(link.name)
                package_lines.append(f"| {row.name} | {version_cell} | {', '.join(registry_parts)} |")
            blocks.append([f"{prefix} Packages", *package_lines])

    if staged:
        app_lines = ["| App | Version | Asset |", "|---|---|---|"]
        for app_name, asset_name, _ in staged:
            version = versions.get(app_name)
            version_cell = version if version is not None else "—"
            asset_url = f"https://github.com/{repository}/releases/download/{tag}/{asset_name}"
            app_lines.append(f"| {app_name} | {version_cell} | [{asset_name}]({asset_url}) |")
        blocks.append([f"{prefix} Apps", *app_lines])

    if context.manifest:
        blocks.append([f"{prefix} Built images", *render_images_table(context.manifest)])

    section = "\n\n".join("\n".join(block) for block in blocks)

    if not publish:
        anchor = f"sha-{context.short}"
        parts = re.split(r'<a id="([^"]+)"></a>', body)
        sections: list[tuple[str, str]] = [
            (parts[index], parts[index + 1].strip() if index + 1 < len(parts) else "")
            for index in range(1, len(parts), 2)
        ]
        new_entry = (anchor, section)
        for index, (existing_anchor, _) in enumerate(sections):
            if existing_anchor == anchor:
                sections[index] = new_entry
                break
        else:
            sections.insert(0, new_entry)
        section = "\n\n".join([f'<a id="{anchor_id}"></a>\n{content}' for anchor_id, content in sections])

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
