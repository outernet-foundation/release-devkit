from __future__ import annotations

import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp

from bashrun.bash import bash, bash_check, bash_output
from ci_devkit.ci_step import ci_step

from .builds import pull_build_assets
from .config import BuildArtifactConfig, PublishConfig
from .outputs import append_line

DEV_DRAFT_TAG = "dev-builds"
_ANCHOR_PATTERN = re.compile(r'<a id="([^"]+)"></a>')


def publish_draft_assets(
    config: PublishConfig,
    run_number: str,
    registry_username: str,
    registry_token: str,
    tag: str,
    repository: str,
    sha: str,
) -> list[tuple[str, Path]]:
    pulled = pull_build_assets(config, run_number, registry_username, registry_token)
    staged = stage_draft_assets(pulled, run_number)
    ensure_draft_release(tag, repository, sha)
    upload_draft_assets(tag, repository, staged)
    return staged


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


def delete_draft_release(tag: str, repository: str) -> None:
    with ci_step(f"Delete draft release {tag}"):
        if not bash_check(f"gh release view {tag} --repo {repository}"):
            print(f"  Draft release {tag} not found — nothing to delete")
            return
        bash(f"gh release delete {tag} --cleanup-tag --yes --repo {repository}")
        print(f"  Draft release {tag} deleted")


def append_draft_section(tag: str, repository: str, anchor: str, section: str) -> None:
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
