from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp

from bashrun.bash import bash, bash_check, bash_output
from ci_devkit.ci_step import ci_step

from release_devkit.builds import pull_build_assets
from release_devkit.config import PublishConfig
from release_devkit.rendering import DIGEST_PATTERN

DEV_DRAFT_TAG = "dev-builds"
_ANCHOR_PATTERN = re.compile(r'<a id="([^"]+)"></a>')


class DraftRelease:
    def __init__(self, tag: str, repository: str, target_sha: str) -> None:
        if not bash_check(f"gh release view {tag} --repo {repository}"):
            bash(f"gh release create {tag} --draft --target {target_sha} --title {tag} --notes '' --repo {repository}")
            print(f"  Draft release {tag} created")
        payload = json.loads(bash_output(f"gh release view {tag} --repo {repository} --json body,url"))
        self.tag = tag
        self.repository = repository
        self.body = payload["body"]
        self.url = payload["url"]
        self.sections = parse_sections(self.body)

    def existing_digests(self) -> set[str]:
        return set(DIGEST_PATTERN.findall(self.body))

    def upsert_section(self, anchor: str, section: str) -> None:
        new_entry = (anchor, section.strip())
        for index, (existing_anchor, _) in enumerate(self.sections):
            if existing_anchor == anchor:
                self.sections[index] = new_entry
                break
        else:
            self.sections.insert(0, new_entry)
        blocks = [f'<a id="{anchor_id}"></a>\n{content}' for anchor_id, content in self.sections]
        with NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as file:
            file.write("\n\n".join(blocks) + "\n")
            notes_path = file.name
        bash(f"gh release edit {self.tag} --repo {self.repository} --notes-file {notes_path}")
        Path(notes_path).unlink()
        print(f"  Section {anchor} written to draft {self.tag}")


def publish_draft_assets(
    config: PublishConfig,
    build_sha: str,
    registry_username: str,
    registry_token: str,
    draft: DraftRelease,
) -> list[tuple[str, Path]]:
    pulled = pull_build_assets(config, build_sha, registry_username, registry_token)

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
        name = f"{stem}-{build_sha[:12]}{suffix}"
        target = staging / name
        shutil.copy2(source, target)
        staged.append((name, target))
        print(f"  Asset: {name}")

    with ci_step(f"Upload assets to {draft.tag}"):
        files = " ".join(f'"{path}"' for _, path in staged)
        bash(f"gh release upload {draft.tag} {files} --clobber --repo {draft.repository}")

    return staged


def parse_sections(body: str) -> list[tuple[str, str]]:
    parts = _ANCHOR_PATTERN.split(body)
    sections: list[tuple[str, str]] = []
    for index in range(1, len(parts), 2):
        anchor_id = parts[index]
        content = parts[index + 1].strip() if index + 1 < len(parts) else ""
        sections.append((anchor_id, content))
    return sections


def delete_draft_release(tag: str, repository: str) -> None:
    with ci_step(f"Delete draft release {tag}"):
        if not bash_check(f"gh release view {tag} --repo {repository}"):
            print(f"  Draft release {tag} not found — nothing to delete")
            return
        bash(f"gh release delete {tag} --cleanup-tag --yes --repo {repository}")
        print(f"  Draft release {tag} deleted")
