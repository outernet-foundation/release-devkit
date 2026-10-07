from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp

from bashrun.bash import bash, bash_check, bash_output
from ci_devkit.ci_step import ci_step

from release_devkit.builds import DigestEntry, pull_build_assets
from release_devkit.config import AppConfig
from release_devkit.context import VerbContext
from release_devkit.rendering import DIGEST_PATTERN, AssetLink, PackageRow, parse_asset_links, render_draft_section

DEV_DRAFT_TAG = "dev-builds"
_ANCHOR_PATTERN = re.compile(r'<a id="([^"]+)"></a>')
_ASSET_NAME_PATTERN = re.compile(r"^(.+)-[0-9a-f]{12}\.[^.]+$")


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

    def has_new_digests(self, manifest: dict[str, DigestEntry]) -> bool:
        existing = self.existing_digests()
        return any(entry.digest not in existing for entry in manifest.values())

    def asset_url(self, name: str) -> str:
        return f"https://github.com/{self.repository}/releases/download/{self.tag}/{name}"

    def asset_links(self, staged: list[tuple[str, Path]]) -> list[AssetLink]:
        return [AssetLink(name, self.asset_url(name)) for name, _ in staged]

    def carried_asset_links(self, exclude_stems: set[str]) -> list[AssetLink]:
        if not self.sections:
            return []
        content = self.sections[0][1]
        return [link for link in parse_asset_links(content) if asset_stem(link.name) not in exclude_stems]

    def upsert_section(
        self,
        anchor: str,
        heading_fragments: list[str],
        assets: list[AssetLink] | None = None,
        images: dict[str, DigestEntry] | None = None,
        packages: list[PackageRow] | None = None,
    ) -> None:
        new_entry = (anchor, render_draft_section(heading_fragments, assets, images, packages).strip())
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
    context: VerbContext, apps: dict[str, AppConfig], draft: DraftRelease
) -> list[tuple[str, Path]]:
    pulled = pull_build_assets(
        context.publish_config.model_copy(update={"apps": apps}),
        context.certified,
        context.settings.github_actor,
        context.settings.github_token,
    )

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
        name = f"{stem}-{context.short}{suffix}"
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
