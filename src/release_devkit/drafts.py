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
from release_devkit.tags import latest_version

DEV_DRAFT_TAG = "dev-builds"

REGISTRY_URL_TEMPLATES: dict[str, str] = {
    "nuget": "https://www.nuget.org/packages/{0}/{1}",
    "npm": "https://www.npmjs.com/package/{0}/v/{1}",
    "pypi": "https://pypi.org/project/{0}/{1}",
}


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

    view_command = f"gh release view {tag} --repo {repository}"
    body = ""
    if bash_check(view_command):
        body = json.loads(bash_output(f"{view_command} --json body"))["body"]
    else:
        bash(f"gh release create {tag} --draft --target {context.head} --title {tag} --notes '' --repo {repository}")

    staged: list[tuple[str, str, Path]] = []
    apps_with_builds = {name: app.builds for name, app in context.publish_config.apps.items() if app.builds}
    if apps_with_builds:
        builds_registry = context.publish_config.builds_registry
        if builds_registry is None:
            raise ValueError("builds_registry is required when any app declares builds")
        short = None if publish else context.short
        staging = Path(mkdtemp(prefix="release-builds-"))
        for app_name, artifacts in apps_with_builds.items():
            for artifact in artifacts:
                layer = staging / f"{artifact.project}-{artifact.platform}"
                pull_build(
                    builds_registry,
                    artifact.project,
                    artifact.platform,
                    f"sha-{context.certified}",
                    layer,
                    registry_username=context.settings.github_actor,
                    registry_token=context.settings.github_token,
                )
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
        for name, package in configured.items():
            version = overrides.get(name) or latest_version(f"{name}-v") or UNCHANGED_FALLBACK_VERSION
            registry_cells: list[str] = []
            for registry_name, identity in package.registries.items():
                template = REGISTRY_URL_TEMPLATES.get(registry_name)
                if template is not None and version != UNCHANGED_FALLBACK_VERSION:
                    registry_cells.append(f"[{registry_name}]({template.format(identity, version)})")
                else:
                    registry_cells.append(registry_name)
            table_rows.append([name, version, ", ".join(registry_cells) if registry_cells else "—"])
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
        table_rows = []
        for image_name, entry in context.manifest.items():
            tree_tag = next(
                (tag_name for tag_name in entry.tags if tag_name.startswith("tree-")),
                entry.tags[0] if entry.tags else "",
            )
            url = None
            if entry.ref.startswith("ghcr.io/"):
                remainder = entry.ref[len("ghcr.io/") :]
                ref_parts = remainder.split("/", 1)
                if len(ref_parts) >= 2:
                    url = (
                        f"https://github.com/orgs/{ref_parts[0]}/packages/container/{ref_parts[1].replace('/', '%2F')}"
                    )
            tag_cell = f"[{tree_tag}]({url})" if url is not None and tree_tag else (tree_tag or "—")
            table_rows.append([image_name, tag_cell, f"`{entry.digest}`"])
        blocks.append(f"{prefix} Built images\n{markdown_table(['Image', 'Tag', 'Digest'], table_rows)}")

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
