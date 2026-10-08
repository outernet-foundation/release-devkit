from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp
from typing import Annotated, NamedTuple

import typer
from bashrun.bash import bash, bash_check, bash_output
from ci_devkit.builds import pull_artifact
from ci_devkit.ci_step import ci_step
from ci_devkit.setup import configure_git, install_dotnet, install_node
from pydantic import BaseModel

from release_devkit.config import DEFAULT_CONFIG_PATH, PublishConfig, Settings, load_config
from release_devkit.plan import UNCHANGED_FALLBACK_VERSION, ReleasePlan, compute_release_plan
from release_devkit.publishing import build_registries
from release_devkit.tags import create_and_push_tag, get_latest_version

DEV_DRAFT_TAG = "dev-builds"
DIGEST_PROJECT = "images-digests"
DIGEST_PLATFORM = "all"
DIGEST_FILE_NAME = "images-digests.json"


class ReleaseChannel(StrEnum):
    STABLE = "stable"
    DEV = "dev"
    PR = "pr"


class DigestEntry(BaseModel):
    ref: str
    digest: str
    tags: list[str]


class PackageRow(NamedTuple):
    name: str
    version: str
    registry: str
    url: str | None


class ImageRow(NamedTuple):
    image: str
    tag: str
    digest: str
    url: str | None


app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    channel: Annotated[ReleaseChannel, typer.Option(help="Delivery channel: pr draft, dev prerelease, stable release")],
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    create_or_update_release(config, channel)


def create_or_update_release(config: Path, channel: ReleaseChannel) -> None:
    # Read the runner settings and the publish config
    settings = Settings.model_validate({})
    publish_config = load_config(config)

    # Make git trust the workspace before any git call — checkout set safe.directory in a temporary HOME
    configure_git(settings.github_workspace)

    # Publish every changed package to its registry and tag the stable versions
    release_plan = compute_release_plan(publish_config)

    # Stop a stable run with nothing to ship
    if channel == ReleaseChannel.STABLE and not release_plan.publishing and not release_plan.app_versions:
        return

    # Resolve the certified SHA for the channel
    head = bash_output("git rev-parse HEAD").strip()
    sha = head if channel == ReleaseChannel.PR else bash_output(f"git log -1 --format=%P {head}").strip().split()[1]
    short_sha = sha[:12]

    # Lay out the release notes scaffolding
    heading = f"### [{short_sha}](https://github.com/{settings.github_repository}/commit/{sha})"
    prefix = "#" * (2 if channel == ReleaseChannel.STABLE else 4)
    blocks: list[str] = []

    # Compose the channel's tag, versions, and header
    match channel:
        case ReleaseChannel.PR:
            tag = f"pr-{re.findall(r'^refs/pull/(\d+)/merge$', settings.github_ref)[0]}"
            versions = {name: get_latest_version(f"{name}-v") for name in publish_config.apps}
            blocks.append(heading)
        case ReleaseChannel.DEV:
            tag = DEV_DRAFT_TAG
            versions = release_plan.app_last_versions

            pr_number, pr_title = re.findall(
                r"Merge PR #(\d+): (.+)", bash_output(f"git log -1 --format=%B {head}").strip()
            )[0]
            blocks.append(
                f"{heading} — [PR #{pr_number}: {pr_title}]"
                f"(https://github.com/{settings.github_repository}/pull/{pr_number})"
            )
        case ReleaseChannel.STABLE:
            year_month = datetime.now(UTC).strftime("%Y.%m")
            existing = bash_output(
                f"gh release list --repo {settings.github_repository} --json tagName"
                f" --jq '[.[].tagName] | map(select(startswith(\"{year_month}\"))) | length'"
            ).strip()
            tag = f"{year_month}.{(int(existing) if existing else 0) + 1}"

            versions = {**release_plan.app_last_versions, **release_plan.app_versions}

    repository = settings.github_repository

    # Ensure a draft release exists and read its current body
    view_command = f"gh release view {tag} --repo {repository}"
    body = ""
    if bash_check(view_command):
        body = json.loads(bash_output(f"{view_command} --json body"))["body"]
    else:
        bash(f"gh release create {tag} --draft --target {head} --title {tag} --notes '' --repo {repository}")

    # Publish the changed packages and tag the stable versions
    if channel in (ReleaseChannel.DEV, ReleaseChannel.STABLE):
        with ci_step("Publish packages"):
            packages = publish_packages(settings, publish_config, release_plan, channel, short_sha)
        if packages:
            packages_rows = [
                [name, version, f"[{registry}]({url})" if url else registry]
                for name, version, registry, url in packages
            ]
            blocks.append(f"{prefix} Packages\n{markdown_table(['Package', 'Version', 'Registry'], packages_rows)}")

    # Stage every app's build artifacts as release assets
    shelf = f"ghcr.io/{repository}/builds"
    if publish_config.apps:
        with ci_step("Stage apps"):
            assets = stage_apps(settings, publish_config, shelf, release_plan, channel, sha, short_sha, tag, repository)
        assets_rows = [
            [
                app_name,
                versions.get(app_name) or "—",
                f"[{path.name}](https://github.com/{repository}/releases/download/{tag}/{path.name})",
            ]
            for app_name, path in assets
        ]
        blocks.append(f"{prefix} Apps\n{markdown_table(['App', 'Version', 'Asset'], assets_rows)}")

    # List the images built at this SHA from the shelf
    if publish_config.built_images:
        with ci_step("List built images"):
            images = render_built_images(settings, shelf, sha)
        if images:
            images_rows = [
                [image, f"[{image_tag}]({url})" if url and image_tag else (image_tag or "—"), f"`{digest}`"]
                for image, image_tag, digest, url in images
            ]
            blocks.append(f"{prefix} Built images\n{markdown_table(['Image', 'Tag', 'Digest'], images_rows)}")

    # Join the blocks into one section
    section = "\n\n".join(blocks)

    # Splice the section into the draft body at its SHA anchor
    if channel != ReleaseChannel.STABLE:
        anchor = f"sha-{short_sha}"
        parts = re.split(r'<a id="([^"]+)"></a>', body)
        sections = {parts[index]: parts[index + 1].strip() for index in range(1, len(parts), 2)}
        sections.pop(anchor, None)
        sections = {anchor: section, **sections}
        section = "\n\n".join(f'<a id="{anchor_id}"></a>\n{content}' for anchor_id, content in sections.items())

    # Apply the notes to the release from a temp file
    with NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as file:
        file.write(section + "\n")
        notes_path = file.name

    try:
        bash(
            f"gh release edit {tag}{' --draft=false' if channel == ReleaseChannel.STABLE else ''}"
            f" --repo {repository} --notes-file {notes_path}"
        )
    finally:
        Path(notes_path).unlink()

    # Reset the dev draft once the stable release is cut
    if channel == ReleaseChannel.STABLE:
        delete_draft_release(DEV_DRAFT_TAG, repository)


def publish_packages(
    settings: Settings,
    publish_config: PublishConfig,
    release_plan: ReleasePlan,
    channel: ReleaseChannel,
    short_sha: str,
) -> list[PackageRow]:
    # Provision the toolchains for the registries this run publishes to
    publishing_registries = {publish_config.packages[name].registry for name in release_plan.publishing}
    if "nuget" in publishing_registries:
        install_dotnet("8.0")
    if "npm" in publishing_registries:
        install_node("24", "https://registry.npmjs.org")
    registries = build_registries(settings.nuget_api_key)
    rows: list[PackageRow] = []
    for name, package in publish_config.packages.items():
        plan = release_plan.plans[name]
        registry = registries[package.registry]
        latest_version = get_latest_version(f"{name}-v")

        # List an unchanged package at its latest stable tag
        if not plan.publish and latest_version is not None:
            rows.append(
                PackageRow(name, latest_version, package.registry, registry.url(package.identity, latest_version))
            )
            continue

        # List a never-published package with the fallback version
        if not plan.publish:
            rows.append(PackageRow(name, UNCHANGED_FALLBACK_VERSION, package.registry, None))
            continue

        # Publish the changed package and list the version it returned
        version = registry.publish(
            package.path,
            plan.version,
            release_plan.resolved_versions[name],
            channel == ReleaseChannel.DEV,
            short_sha,
        )

        if channel == ReleaseChannel.STABLE:
            create_and_push_tag(f"{name}-v{plan.version}")

        rows.append(PackageRow(name, version, package.registry, registry.url(package.identity, version)))

    return rows


def stage_apps(
    settings: Settings,
    publish_config: PublishConfig,
    shelf: str,
    release_plan: ReleasePlan,
    channel: ReleaseChannel,
    sha: str,
    short_sha: str,
    tag: str,
    repository: str,
) -> list[tuple[str, Path]]:
    staging = Path(mkdtemp(prefix="release-builds-"))
    staged: list[tuple[str, Path]] = []
    for app_name, artifact in [
        (app_name, artifact) for app_name, app in publish_config.apps.items() for artifact in app.builds
    ]:
        layer = staging / f"{artifact.project}-{artifact.platform}"
        # Pull the artifact layer from the builds shelf
        pull_artifact(
            shelf,
            artifact.project,
            artifact.platform,
            f"sha-{sha}",
            layer,
            registry_username=settings.github_actor,
            registry_token=settings.github_token,
        )

        # The layer holds exactly one file: the build's single player binary
        source = next(path for path in layer.iterdir() if path.is_file())

        # Copy the asset under its release name and record it
        named = Path(artifact.file)
        name = named.name if channel == ReleaseChannel.STABLE else f"{named.stem}-{short_sha}{named.suffix}"
        target = staging / name
        shutil.copy2(source, target)
        staged.append((app_name, target))
        print(f"  Asset: {name}")

    # Tag the bumped app versions alongside their staged assets
    if channel == ReleaseChannel.STABLE:
        for app_name, app_version in release_plan.app_versions.items():
            create_and_push_tag(f"{app_name}-v{app_version}")

    # Upload the staged assets
    bash(f"gh release upload {tag} {' '.join(f'"{path}"' for _, path in staged)} --clobber --repo {repository}")

    return staged


def render_built_images(settings: Settings, shelf: str, sha: str) -> list[ImageRow]:
    # Pull the digest manifest from the shelf
    digest_staging = Path(mkdtemp(prefix="digest-manifest-"))
    pull_artifact(
        shelf,
        DIGEST_PROJECT,
        DIGEST_PLATFORM,
        f"sha-{sha}",
        digest_staging,
        registry_username=settings.github_actor,
        registry_token=settings.github_token,
    )
    data = json.loads((digest_staging / DIGEST_FILE_NAME).read_text(encoding="utf-8"))
    manifest = {target: DigestEntry.model_validate(entry) for target, entry in data.items()}

    # List built images from the digest manifest
    rows: list[ImageRow] = []
    for image_name, entry in manifest.items():
        tree_tag = next(
            (tag_name for tag_name in entry.tags if tag_name.startswith("tree-")),
            entry.tags[0] if entry.tags else "",
        )
        url = (
            f"https://github.com/orgs/{ref_parts[0]}/packages/container/{ref_parts[1].replace('/', '%2F')}"
            if entry.ref.startswith("ghcr.io/") and len(ref_parts := entry.ref[len("ghcr.io/") :].split("/", 1)) >= 2
            else None
        )
        rows.append(ImageRow(image_name, tree_tag, entry.digest, url))
    return rows


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [f"| {' | '.join(headers)} |", f"|{'|'.join('---' for _ in headers)}|"]
    lines.extend(f"| {' | '.join(row)} |" for row in rows)
    return "\n".join(lines)


def delete_draft_release(tag: str, repository: str) -> None:
    if not bash_check(f"gh release view {tag} --repo {repository}"):
        return
    bash(f"gh release delete {tag} --cleanup-tag --yes --repo {repository}")
