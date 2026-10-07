from __future__ import annotations

from dataclasses import dataclass, field

from release_devkit.builds import DigestEntry


@dataclass
class RegistryLink:
    name: str
    version: str
    url: str | None


@dataclass
class PackageRow:
    name: str
    version: str
    registries: list[RegistryLink] = field(default_factory=list)


def render_images_table(manifest: dict[str, DigestEntry]) -> list[str]:
    lines = ["| Image | Tag | Digest |", "|---|---|---|"]
    for target, entry in manifest.items():
        tree_tag = next(
            (tag for tag in entry.tags if tag.startswith("tree-")),
            entry.tags[0] if entry.tags else "",
        )
        url = None
        if entry.ref.startswith("ghcr.io/"):
            remainder = entry.ref[len("ghcr.io/") :]
            parts = remainder.split("/", 1)
            if len(parts) >= 2:
                url = f"https://github.com/orgs/{parts[0]}/packages/container/{parts[1].replace('/', '%2F')}"
        tag_cell = f"[{tree_tag}]({url})" if url is not None and tree_tag else (tree_tag or "—")
        lines.append(f"| {target} | {tag_cell} | `{entry.digest}` |")
    return lines
