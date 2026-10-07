from __future__ import annotations

import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from bashrun.bash import bash, bash_check, bash_output

from release_devkit.builds import stage_build_assets
from release_devkit.context import VerbContext

DEV_DRAFT_TAG = "dev-builds"
ANCHOR_PATTERN = re.compile(r'<a id="([^"]+)"></a>')


def upsert_section(body: str, anchor: str, section: str) -> str:
    parts = ANCHOR_PATTERN.split(body)
    sections: list[tuple[str, str]] = [
        (parts[index], parts[index + 1].strip() if index + 1 < len(parts) else "") for index in range(1, len(parts), 2)
    ]
    new_entry = (anchor, section)
    for index, (existing_anchor, _) in enumerate(sections):
        if existing_anchor == anchor:
            sections[index] = new_entry
            break
    else:
        sections.insert(0, new_entry)
    return "\n\n".join([f'<a id="{anchor_id}"></a>\n{content}' for anchor_id, content in sections])


def stage_and_upload(context: VerbContext, tag: str, short: str | None) -> list[tuple[str, str, Path]]:
    staged = stage_build_assets(context, context.publish_config.apps, short)
    upload_release_assets(context, tag, staged)
    return staged


def edit_release_notes(context: VerbContext, tag: str, body: str, publish: bool) -> None:
    draft_flag = " --draft=false" if publish else ""
    gh_release_with_notes(
        f"gh release edit {tag}{draft_flag} --repo {context.settings.github_repository}",
        body + "\n",
    )


def ensure_draft_release(context: VerbContext, tag: str) -> str:
    repository = context.settings.github_repository
    if not bash_check(f"gh release view {tag} --repo {repository}"):
        bash(f"gh release create {tag} --draft --target {context.head} --title {tag} --notes '' --repo {repository}")
        return ""
    return json.loads(bash_output(f"gh release view {tag} --repo {repository} --json body"))["body"]


def upload_release_assets(context: VerbContext, tag: str, staged: list[tuple[str, str, Path]]) -> None:
    if staged:
        repository = context.settings.github_repository
        bash(f"gh release upload {tag} {' '.join(f'"{path}"' for _, _, path in staged)} --clobber --repo {repository}")


def gh_release_with_notes(command: str, body: str) -> None:
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
