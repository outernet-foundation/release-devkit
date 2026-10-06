from __future__ import annotations

import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp
from typing import Annotated

import typer
from bashrun.bash import bash, bash_check, bash_output
from ci_devkit.ci_step import ci_step
from pydantic_settings import BaseSettings

from .config import DEFAULT_CONFIG_PATH, BuildArtifactConfig, load_config
from .create_release import (
    DigestEntry,
    builds_registry_of,
    pull_build_assets,
    pull_digest_manifest,
    render_images_table,
)
from .outputs import append_line

update_pr_app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

PR_DRAFT_TAG_PREFIX = "pr-"
DEV_DRAFT_TAG = "dev-builds"
_ANCHOR_PATTERN = re.compile(r'<a id="([^"]+)"></a>')


class Settings(BaseSettings):
    github_repository: str
    github_sha: str = ""
    github_actor: str = ""
    github_token: str = ""
    github_run_id: str = ""
    github_step_summary: str | None = None


@update_pr_app.command()
def update_pr_draft(
    pr_number: Annotated[int, typer.Option(help="PR number whose draft to update")],
    run_number: Annotated[int, typer.Option(help="CI run number whose builds to surface")],
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)
    if not any(app.builds for app in publish_config.apps.values()):
        return

    tag = f"{PR_DRAFT_TAG_PREFIX}{pr_number}"
    resolved_run_number = str(run_number)
    pulled = pull_build_assets(publish_config, resolved_run_number, settings.github_actor, settings.github_token)
    staged = stage_draft_assets(pulled, resolved_run_number)
    manifest = pull_digest_manifest(
        builds_registry_of(publish_config), resolved_run_number, settings.github_actor, settings.github_token
    )
    ensure_draft_release(tag, settings.github_repository, settings.github_sha)
    upload_draft_assets(tag, settings.github_repository, staged)
    run_url = f"https://github.com/{settings.github_repository}/actions/runs/{settings.github_run_id}"
    section = build_draft_section(
        settings.github_repository, tag, resolved_run_number, run_url, pr_number, staged, manifest or {}
    )
    append_draft_section(tag, settings.github_repository, settings.github_sha, f"run-{resolved_run_number}", section)
    emit_draft_summary(settings.github_step_summary, tag, settings.github_repository, staged)


def stage_draft_assets(assets: list[tuple[BuildArtifactConfig, Path]], run_number: str) -> list[tuple[str, Path]]:
    staging = Path(mkdtemp(prefix="draft-assets-"))
    staged: list[tuple[str, Path]] = []
    for artifact, source in assets:
        if artifact.name is not None:
            configured = Path(artifact.name)
            stem = configured.stem
            suffix = configured.suffix
        else:
            stem = source.stem
            suffix = source.suffix
        name = f"{stem}-run-{run_number}{suffix}"
        target = staging / name
        shutil.copy2(source, target)
        staged.append((name, target))
        print(f"  Asset: {name}")
    return staged


def ensure_draft_release(tag: str, repository: str, sha: str) -> None:
    with ci_step(f"Ensure draft release {tag}"):
        if bash_check(f"gh release view {tag} --repo {repository}"):
            print(f"  Draft release {tag} already exists")
            return
        bash(f"gh release create {tag} --draft --target {sha} --title {tag} --notes '' --repo {repository}")
        print(f"  Draft release {tag} created")


def upload_draft_assets(tag: str, repository: str, staged: list[tuple[str, Path]]) -> None:
    with ci_step(f"Upload assets to {tag}"):
        files = " ".join(f'"{path}"' for _, path in staged)
        bash(f"gh release upload {tag} {files} --clobber --repo {repository}")


def emit_draft_summary(summary_path: str | None, tag: str, repository: str, staged: list[tuple[str, Path]]) -> None:
    lines = [f"### Draft release `{tag}`", ""]
    for name, _ in staged:
        url = f"https://github.com/{repository}/releases/download/{tag}/{name}"
        lines.append(f"- [{name}]({url})")
    summary = "\n".join(lines)
    print(summary)
    append_line(summary_path, summary)


def build_draft_section(
    repository: str,
    tag: str,
    run_number: str,
    run_url: str,
    pr_number: int,
    staged: list[tuple[str, Path]],
    image_manifest: dict[str, DigestEntry],
) -> str:
    pr_url = f"https://github.com/{repository}/pull/{pr_number}"
    lines = [f"### [Run #{run_number}]({run_url}) — [PR #{pr_number}]({pr_url})"]
    if image_manifest:
        lines.append("")
        lines.append("#### Built images")
        lines.extend(render_images_table(image_manifest))
    if staged:
        lines.append("")
        for name, _ in staged:
            url = f"https://github.com/{repository}/releases/download/{tag}/{name}"
            lines.append(f"- [{name}]({url})")
    return "\n".join(lines)


def delete_draft_release(tag: str, repository: str) -> None:
    with ci_step(f"Delete draft release {tag}"):
        if not bash_check(f"gh release view {tag} --repo {repository}"):
            print(f"  Draft release {tag} not found — nothing to delete")
            return
        bash(f"gh release delete {tag} --cleanup-tag --yes --repo {repository}")
        print(f"  Draft release {tag} deleted")


def append_draft_section(tag: str, repository: str, sha: str, anchor: str, section: str) -> None:
    ensure_draft_release(tag, repository, sha)
    body = bash_output(f"gh release view {tag} --repo {repository} --json body --jq .body")
    updated = replace_or_prepend_section(body, anchor, section.strip())
    with NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as file:
        file.write(updated)
        notes_path = file.name
    bash(f"gh release edit {tag} --repo {repository} --notes-file {notes_path}")
    Path(notes_path).unlink()
    print(f"  Section {anchor} written to draft {tag}")


def replace_or_prepend_section(body: str, anchor: str, section: str) -> str:
    sections = _parse_sections(body)
    new_entry = (anchor, section)
    for index, (existing_anchor, _) in enumerate(sections):
        if existing_anchor == anchor:
            sections[index] = new_entry
            break
    else:
        sections.insert(0, new_entry)
    return _join_sections(sections)


def _parse_sections(body: str) -> list[tuple[str, str]]:
    parts = _ANCHOR_PATTERN.split(body)
    sections: list[tuple[str, str]] = []
    for index in range(1, len(parts), 2):
        anchor_id = parts[index]
        content = parts[index + 1].strip() if index + 1 < len(parts) else ""
        sections.append((anchor_id, content))
    return sections


def _join_sections(sections: list[tuple[str, str]]) -> str:
    if not sections:
        return ""
    blocks = [f'<a id="{anchor_id}"></a>\n{content}' for anchor_id, content in sections]
    return "\n\n".join(blocks) + "\n"


def emit_draft_backlink(summary_path: str | None, tag: str, repository: str, anchor: str) -> None:
    url = bash_output(f"gh release view {tag} --repo {repository} --json url --jq .url").strip()
    link = f"{url}#{anchor}"
    text = f"### Draft release `{tag}` updated\n- [Section `{anchor}`]({link})"
    print(text)
    append_line(summary_path, text)
