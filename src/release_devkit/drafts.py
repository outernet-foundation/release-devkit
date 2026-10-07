from __future__ import annotations

import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from bashrun.bash import bash, bash_check, bash_output

from release_devkit.builds import stage_build_assets
from release_devkit.context import VerbContext
from release_devkit.plan import PackageRow, package_rows, package_version_overrides
from release_devkit.rendering import collect_app_rows, render_release_body

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

    staged = stage_build_assets(context, context.publish_config.apps, short)
    if staged:
        bash(f"gh release upload {tag} {' '.join(f'"{path}"' for _, _, path in staged)} --clobber --repo {repository}")

    app_rows = collect_app_rows(staged, versions, repository, tag)

    packages: list[PackageRow] | None = None
    if published is not None:
        configured = context.publish_config.packages
        packages = package_rows(configured, package_version_overrides(configured, published))

    section = render_release_body(heading, packages, app_rows, context.manifest, level=2 if publish else 4)

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
