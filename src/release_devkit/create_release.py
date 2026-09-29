from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated

import typer
from bashrun.bash import bash, bash_output
from pydantic_settings import BaseSettings
from ci_devkit.ci_step import ci_step

from .artifacts import ARTIFACT_DIR, is_release_artifact
from .config import load_config
from .ledger import GitLedger
from .plan import UNCHANGED_FALLBACK_VERSION

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


class Settings(BaseSettings):
    github_repository: str


@app.command()
def main(config: Annotated[Path, typer.Option(help="Publish configuration YAML")]) -> None:
    run_create_release(config)


def run_create_release(config: Path) -> None:
    settings = Settings.model_validate({})
    publish_config = load_config(config)

    year_month = datetime.now(UTC).strftime("%Y.%m")
    existing = bash_output(
        f"gh release list --repo {settings.github_repository} --json tagName"
        f" --jq '[.[].tagName] | map(select(startswith(\"{year_month}\"))) | length'"
    ).strip()
    count = int(existing) if existing else 0
    tag = f"{year_month}.{count + 1}"

    with ci_step("Package artifacts"):
        assets: list[Path] = []
        artifact_dir = ARTIFACT_DIR
        if not artifact_dir.is_dir():
            print("No release artifacts directory found")
        else:
            for entry in sorted(artifact_dir.iterdir()):
                if not entry.is_dir():
                    continue
                if not is_release_artifact(entry.name):
                    print(f"  Skipping: {entry.name} (not a release artifact)")
                    continue

                files = [path for path in entry.rglob("*") if path.is_file()]
                if not files:
                    print(f"  Skipping: {entry.name} (empty)")
                    continue

                if len(files) == 1:
                    asset = artifact_dir / f"{entry.name}{files[0].suffix}"
                    shutil.copy2(files[0], asset)
                else:
                    zip_path = artifact_dir / entry.name
                    shutil.make_archive(str(zip_path), "zip", entry)
                    asset = zip_path.parent / f"{zip_path.name}.zip"
                assets.append(asset)
                print(f"  Asset: {asset.name}" + (f" ({len(files)} files)" if len(files) > 1 else ""))

        if assets:
            print(f"  {len(assets)} asset(s) ready for upload")
        else:
            print("  No build artifacts to attach")

    with ci_step("Create GitHub Release"):
        registry_urls: dict[str, Callable[[str, str], str]] = {
            "nuget": lambda identity, version: f"https://www.nuget.org/packages/{identity}/{version}",
            "npm": lambda identity, version: f"https://www.npmjs.com/package/{identity}/v/{version}",
            "pypi": lambda identity, version: f"https://pypi.org/project/{identity}/{version}",
        }

        ledger = GitLedger()
        lines: list[str] = []

        lines.extend(["## Packages", "", "| Package | Version | Registry |", "|---|---|---|"])
        for name, package in publish_config.packages.items():
            version = ledger.latest_version(f"{name}-v") or UNCHANGED_FALLBACK_VERSION
            links: list[str] = []
            for registry_name, identity in package.registries.items():
                url_builder = registry_urls.get(registry_name)
                if url_builder is None:
                    links.append(registry_name)
                elif version != UNCHANGED_FALLBACK_VERSION:
                    links.append(f"[{registry_name}]({url_builder(identity, version)})")
                else:
                    links.append(registry_name)
            lines.append(f"| {name} | {version} | {', '.join(links)} |")

        for app_name in publish_config.apps:
            version = ledger.latest_version(f"{app_name}-v")
            if version:
                lines.append(f"| {app_name} | {version} | — |")

        lines.append("")
        notes = "\n".join(lines)
        print(notes)

        asset_args = " ".join(f'"{asset}"' for asset in assets)
        with NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as file:
            file.write(notes)
            notes_path = file.name
        bash(
            f"gh release create {tag} --title {tag}"
            f" --notes-file {notes_path}"
            f" --repo {settings.github_repository}"
            f" {asset_args}"
        )
        Path(notes_path).unlink()
        print(f"  Release created: {tag}")
