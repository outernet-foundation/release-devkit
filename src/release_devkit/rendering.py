from __future__ import annotations

import re
from dataclasses import dataclass, field

from release_devkit.builds import DigestEntry

DIGEST_PATTERN = re.compile(r"sha256:[a-f0-9]{64}")
ASSET_LINK_PATTERN = re.compile(r"^- \[([^\]]+)\]\(([^)]+)\)$", re.MULTILINE)


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


@dataclass
class AssetLink:
    name: str
    url: str


def render_packages_table(rows: list[PackageRow]) -> list[str]:
    lines = ["| Package | Version | Registry |", "|---|---|---|"]
    for row in rows:
        if not row.registries:
            lines.append(f"| {row.name} | {row.version} | \u2014 |")
            continue
        versions = {link.version for link in row.registries}
        if len(versions) == 1:
            version_cell = next(iter(versions))
        else:
            version_cell = ", ".join(f"{link.version} ({link.name})" for link in row.registries)
        registry_parts: list[str] = []
        for link in row.registries:
            if link.url is not None:
                registry_parts.append(f"[{link.name}]({link.url})")
            else:
                registry_parts.append(link.name)
        lines.append(f"| {row.name} | {version_cell} | {', '.join(registry_parts)} |")
    return lines


def render_asset_links(links: list[AssetLink]) -> list[str]:
    return [f"- [{link.name}]({link.url})" for link in links]


def parse_asset_links(content: str) -> list[AssetLink]:
    return [AssetLink(name=name, url=url) for name, url in ASSET_LINK_PATTERN.findall(content)]


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


def render_release_body(rows: list[PackageRow], images: dict[str, DigestEntry] | None) -> str:
    lines = ["## Packages", ""]
    lines.extend(render_packages_table(rows))
    if images:
        lines.append("")
        lines.append("## Built images")
        lines.extend(render_images_table(images))
    lines.append("")
    return "\n".join(lines)
