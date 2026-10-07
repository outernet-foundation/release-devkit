from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from release_devkit.builds import DigestEntry

DIGEST_PATTERN = re.compile(r"sha256:[a-f0-9]{64}")
APP_TABLE_HEADER = "| App | Version | Asset |"


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
class AppRow:
    name: str
    version: str | None
    asset_name: str | None
    asset_url: str | None


def collect_app_rows(
    staged: list[tuple[str, str, Path]],
    versions: dict[str, str | None],
    repository: str,
    tag: str,
) -> list[AppRow]:
    return [
        app_row(app_name, versions.get(app_name), asset_name, repository, tag) for app_name, asset_name, _ in staged
    ]


def app_row(
    name: str,
    version: str | None,
    asset_name: str | None,
    repository: str,
    tag: str,
) -> AppRow:
    return AppRow(
        name,
        version,
        asset_name,
        f"https://github.com/{repository}/releases/download/{tag}/{asset_name}" if asset_name is not None else None,
    )


def render_release_body(
    heading: str | None,
    packages: list[PackageRow] | None,
    app_rows: list[AppRow],
    manifest: dict[str, DigestEntry] | None,
    level: int,
) -> str:
    prefix = "#" * level
    blocks: list[list[str]] = []
    if heading is not None:
        blocks.append([heading])
    if packages:
        blocks.append([f"{prefix} Packages", *render_packages_table(packages)])
    if app_rows:
        blocks.append([f"{prefix} Apps", *render_app_table(app_rows)])
    if manifest:
        blocks.append([f"{prefix} Built images", *render_images_table(manifest)])
    return "\n\n".join("\n".join(block) for block in blocks)


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


def render_app_table(rows: list[AppRow]) -> list[str]:
    lines = [APP_TABLE_HEADER, "|---|---|---|"]
    for row in rows:
        version_cell = row.version if row.version is not None else "—"
        if row.asset_name is not None and row.asset_url is not None:
            asset_cell = f"[{row.asset_name}]({row.asset_url})"
        else:
            asset_cell = "—"
        lines.append(f"| {row.name} | {version_cell} | {asset_cell} |")
    return lines


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
