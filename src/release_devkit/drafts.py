from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp

from bashrun.bash import bash, bash_check, bash_output
from ci_devkit.ci_step import ci_step

from release_devkit.builds import pull_build_assets
from release_devkit.context import VerbContext
from release_devkit.plan import apps_with_changes
from release_devkit.rendering import DIGEST_PATTERN, AssetLink, PackageRow, parse_asset_links, render_draft_section

DEV_DRAFT_TAG = "dev-builds"
_ANCHOR_PATTERN = re.compile(r'<a id="([^"]+)"></a>')
_ASSET_NAME_PATTERN = re.compile(r"^(.+)-[0-9a-f]{12}\.[^.]+$")


def write_draft_section(
    context: VerbContext,
    tag: str,
    heading_fragments: list[str],
    stage_changed_only: bool,
    publishing: bool = False,
    packages: list[PackageRow] | None = None,
) -> None:
    repository = context.settings.github_repository
    changed_apps = apps_with_changes(context.publish_config)
    if not bash_check(f"gh release view {tag} --repo {repository}"):
        bash(f"gh release create {tag} --draft --target {context.head} --title {tag} --notes '' --repo {repository}")
        print(f"  Draft release {tag} created")
    body = json.loads(bash_output(f"gh release view {tag} --repo {repository} --json body"))["body"]
    if (
        not publishing
        and not changed_apps
        and not any(
            entry.digest not in set(DIGEST_PATTERN.findall(body)) for entry in (context.manifest or {}).values()
        )
    ):
        print("Nothing to publish")
        return
    apps = changed_apps if stage_changed_only else context.publish_config.apps
    staged: list[tuple[str, Path]] = []
    if apps:
        staging = Path(mkdtemp(prefix="draft-assets-"))
        for artifact, source in pull_build_assets(
            apps,
            context.publish_config.builds_registry,
            context.certified,
            context.settings.github_actor,
            context.settings.github_token,
        ):
            named = Path(artifact.name) if artifact.name is not None else source
            name = f"{named.stem}-{context.short}{named.suffix}"
            target = staging / name
            shutil.copy2(source, target)
            staged.append((name, target))
            print(f"  Asset: {name}")
    if staged:
        with ci_step(f"Upload assets to {tag}"):
            bash(f"gh release upload {tag} {' '.join(f'"{path}"' for _, path in staged)} --clobber --repo {repository}")
    anchor = f"sha-{context.short}"
    parts = _ANCHOR_PATTERN.split(body)
    sections: list[tuple[str, str]] = [
        (parts[index], parts[index + 1].strip() if index + 1 < len(parts) else "") for index in range(1, len(parts), 2)
    ]
    new_entry = (
        anchor,
        render_draft_section(
            heading_fragments,
            (
                [
                    AssetLink(name, f"https://github.com/{repository}/releases/download/{tag}/{name}")
                    for name, _ in staged
                ]
                + (
                    [
                        link
                        for link in parse_asset_links(sections[0][1])
                        if asset_stem(link.name)
                        not in {stem for name, _ in staged if (stem := asset_stem(name)) is not None}
                    ]
                    if sections
                    else []
                )
            )
            or None,
            context.manifest,
            packages or None,
        ).strip(),
    )
    for index, (existing_anchor, _) in enumerate(sections):
        if existing_anchor == anchor:
            sections[index] = new_entry
            break
    else:
        sections.insert(0, new_entry)
    with NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as file:
        file.write("\n\n".join([f'<a id="{anchor_id}"></a>\n{content}' for anchor_id, content in sections]) + "\n")
        notes_path = file.name
    bash(f"gh release edit {tag} --repo {repository} --notes-file {notes_path}")
    Path(notes_path).unlink()
    print(f"  Section {anchor} written to draft {tag}")


def asset_stem(name: str) -> str | None:
    match = _ASSET_NAME_PATTERN.fullmatch(name)
    return match.group(1) if match is not None else None


def delete_draft_release(tag: str, repository: str) -> None:
    with ci_step(f"Delete draft release {tag}"):
        if not bash_check(f"gh release view {tag} --repo {repository}"):
            print(f"  Draft release {tag} not found — nothing to delete")
            return
        bash(f"gh release delete {tag} --cleanup-tag --yes --repo {repository}")
        print(f"  Draft release {tag} deleted")
