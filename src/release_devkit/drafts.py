from __future__ import annotations

import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp

from bashrun.bash import bash, bash_check, bash_output
from ci_devkit.ci_step import ci_step

from release_devkit.builds import pull_build_assets
from release_devkit.config import PublishConfig

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

    staging = Path(mkdtemp(prefix="draft-assets-"))
    staged: list[tuple[str, Path]] = []
    for artifact, source in pulled:
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

    with ci_step(f"Ensure draft release {tag}"):
        if bash_check(f"gh release view {tag} --repo {repository}"):
            print(f"  Draft release {tag} already exists")
        else:
            bash(f"gh release create {tag} --draft --target {sha} --title {tag} --notes '' --repo {repository}")
            print(f"  Draft release {tag} created")

    with ci_step(f"Upload assets to {tag}"):
        files = " ".join(f'"{path}"' for _, path in staged)
        bash(f"gh release upload {tag} {files} --clobber --repo {repository}")

    return staged


def append_draft_section(tag: str, repository: str, anchor: str, section: str) -> None:
    body = bash_output(f"gh release view {tag} --repo {repository} --json body --jq .body")

    parts = _ANCHOR_PATTERN.split(body)
    sections: list[tuple[str, str]] = []
    for index in range(1, len(parts), 2):
        anchor_id = parts[index]
        content = parts[index + 1].strip() if index + 1 < len(parts) else ""
        sections.append((anchor_id, content))

    new_entry = (anchor, section.strip())
    for index, (existing_anchor, _) in enumerate(sections):
        if existing_anchor == anchor:
            sections[index] = new_entry
            break
    else:
        sections.insert(0, new_entry)

    if not sections:
        updated = ""
    else:
        blocks = [f'<a id="{anchor_id}"></a>\n{content}' for anchor_id, content in sections]
        updated = "\n\n".join(blocks) + "\n"

    with NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as file:
        file.write(updated)
        notes_path = file.name
    bash(f"gh release edit {tag} --repo {repository} --notes-file {notes_path}")
    Path(notes_path).unlink()
    print(f"  Section {anchor} written to draft {tag}")


def delete_draft_release(tag: str, repository: str) -> None:
    with ci_step(f"Delete draft release {tag}"):
        if not bash_check(f"gh release view {tag} --repo {repository}"):
            print(f"  Draft release {tag} not found — nothing to delete")
            return
        bash(f"gh release delete {tag} --cleanup-tag --yes --repo {repository}")
        print(f"  Draft release {tag} deleted")
