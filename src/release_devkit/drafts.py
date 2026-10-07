from __future__ import annotations

import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from bashrun.bash import bash, bash_check, bash_output

from release_devkit.builds import stage_build_assets
from release_devkit.context import VerbContext
from release_devkit.rendering import (
    APP_TABLE_HEADER,
    DIGEST_PATTERN,
    AppRow,
    PackageRow,
    app_row,
    render_release_body,
)
from release_devkit.tags import has_changes_since, latest_version

DEV_DRAFT_TAG = "dev-builds"
_ANCHOR_PATTERN = re.compile(r'<a id="([^"]+)"></a>')
_ASSET_NAME_PATTERN = re.compile(r"^(.+)-[0-9a-f]{12}\.[^.]+$")
_APP_ROW_PATTERN = re.compile(r"\| ([^|]+) \| ([^|]*) \| \[([^\]]+)\]\(([^)]+)\) \|")


def write_draft_section(
    context: VerbContext,
    tag: str,
    heading_fragments: list[str],
    stage_changed_only: bool,
    publishing: bool = False,
    packages: list[PackageRow] | None = None,
) -> None:
    # Detect apps whose source changed since their last version tag
    app_last_versions = {name: latest_version(f"{name}-v") for name in context.publish_config.apps}
    changed_apps = {
        name: app
        for name, app in context.publish_config.apps.items()
        if app.builds is not None
        and has_changes_since(
            f"{name}-v{app_last_versions[name]}" if app_last_versions[name] else None,
            app.path,
        )
    }

    # Read the current body, treating a missing draft as empty
    repository = context.settings.github_repository
    draft_exists = bash_check(f"gh release view {tag} --repo {repository}")
    body = (
        json.loads(bash_output(f"gh release view {tag} --repo {repository} --json body"))["body"]
        if draft_exists
        else ""
    )

    # Skip the write when nothing changed
    if (
        not publishing
        and not changed_apps
        and not any(
            entry.digest not in set(DIGEST_PATTERN.findall(body)) for entry in (context.manifest or {}).values()
        )
    ):
        return

    # Ensure the draft release exists
    if not draft_exists:
        bash(f"gh release create {tag} --draft --target {context.head} --title {tag} --notes '' --repo {repository}")

    # Stage app assets pulled from the builds shelf
    apps = changed_apps if stage_changed_only else context.publish_config.apps
    staged = stage_build_assets(context, apps, context.short)

    # Upload staged assets onto the draft
    if staged:
        bash(f"gh release upload {tag} {' '.join(f'"{path}"' for _, _, path in staged)} --clobber --repo {repository}")

    # Split the body into anchor-keyed sections
    anchor = f"sha-{context.short}"
    parts = _ANCHOR_PATTERN.split(body)
    sections: list[tuple[str, str]] = [
        (parts[index], parts[index + 1].strip() if index + 1 < len(parts) else "") for index in range(1, len(parts), 2)
    ]

    # Collect fresh app rows and carry forward rows not re-staged this run
    app_rows = [
        app_row(app_name, app_last_versions.get(app_name), asset_name, repository, tag)
        for app_name, asset_name, _ in staged
    ]
    if sections:
        restaged_stems = {stem for _, asset_name, _ in staged if (stem := asset_stem(asset_name)) is not None}
        lines = sections[0][1].splitlines()
        if APP_TABLE_HEADER in lines:
            for line in lines[lines.index(APP_TABLE_HEADER) + 1 :]:
                stripped = line.strip()
                if not stripped.startswith("|"):
                    break
                if set(stripped) <= set("|-: "):
                    continue
                match = _APP_ROW_PATTERN.fullmatch(stripped)
                if match is not None and asset_stem(match[3]) not in restaged_stems:
                    app_rows.append(AppRow(match[1], match[2] or None, match[3], match[4]))

    # Render the new section body
    body = render_release_body(f"### {' — '.join(heading_fragments)}", packages, app_rows, context.manifest, level=4)

    # Replace this SHA's section or prepend a new one
    new_entry = (anchor, body)
    for index, (existing_anchor, _) in enumerate(sections):
        if existing_anchor == anchor:
            sections[index] = new_entry
            break
    else:
        sections.insert(0, new_entry)

    # Write the merged body back to the release
    run_with_notes_file(
        f"gh release edit {tag} --repo {repository}",
        "\n\n".join([f'<a id="{anchor_id}"></a>\n{content}' for anchor_id, content in sections]) + "\n",
    )


def asset_stem(name: str) -> str | None:
    match = _ASSET_NAME_PATTERN.fullmatch(name)
    return match.group(1) if match is not None else None


def run_with_notes_file(command: str, body: str) -> None:
    with NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as file:
        file.write(body)
        notes_path = file.name
    try:
        bash(f"{command} --notes-file {notes_path}")
    finally:
        Path(notes_path).unlink()


def delete_draft_release(tag: str, repository: str) -> None:
    if not bash_check(f"gh release view {tag} --repo {repository}"):
        return
    bash(f"gh release delete {tag} --cleanup-tag --yes --repo {repository}")
