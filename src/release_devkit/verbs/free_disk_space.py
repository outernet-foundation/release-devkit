from __future__ import annotations

import os
import platform
import shlex
import shutil
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash, bash_no_raise
from pydantic import Field
from pydantic_settings import BaseSettings

CONTAINER_PATHS = ["/to_clean/android", "/to_clean/dotnet", "/to_clean/ghcup", "/to_clean/swift"]

BARE_LINUX_PATHS = ["/usr/local/lib/android", "/usr/share/dotnet", "/usr/local/.ghcup", "/usr/share/swift", "/opt/ghc"]

LARGE_PACKAGE_PATTERNS = [
    "^aspnetcore-.*",
    "^dotnet-.*",
    "^llvm-.*",
    "php.*",
    "^mongodb-.*",
    "^mysql-.*",
    "azure-cli",
    "google-chrome-stable",
    "firefox",
    "powershell",
    "mono-devel",
    "libgl1-mesa-dri",
    "google-cloud-sdk",
    "google-cloud-cli",
]


class Settings(BaseSettings):
    system_drive: str = Field("C:", validation_alias="SystemDrive")
    agent_tools_directory: str | None = Field(None, validation_alias="AGENT_TOOLSDIRECTORY")


settings = Settings.model_validate({})

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)


@app.command()
def main(
    large_packages: Annotated[bool, typer.Option(help="Also remove large apt packages")] = False,
    docker_images: Annotated[bool, typer.Option(help="Also prune all docker images")] = False,
    swap_storage: Annotated[bool, typer.Option(help="Also remove the swap file")] = False,
) -> None:
    free_disk_space(large_packages=large_packages, docker_images=docker_images, swap_storage=swap_storage)


def free_disk_space(*, large_packages: bool = False, docker_images: bool = False, swap_storage: bool = False) -> None:
    system = platform.system()
    in_container = Path("/to_clean").is_dir()

    if system == "Windows":
        paths = [os.path.join(settings.system_drive, "Program Files", "dotnet")]
        if settings.agent_tools_directory:
            paths.append(settings.agent_tools_directory)
        print(f"Removing: {', '.join(paths)}")
        _remove_paths(paths)
    elif in_container:
        print("Removing pre-installed toolchains (container)")
        _remove_paths(CONTAINER_PATHS)
    else:
        print("Removing pre-installed toolchains")
        _remove_paths(BARE_LINUX_PATHS, sudo=True)

        if large_packages:
            print("Removing large apt packages")
            bash_no_raise(f"sudo apt-get remove -y --fix-missing {shlex.join(LARGE_PACKAGE_PATTERNS)}")
            bash_no_raise("sudo apt-get autoremove -y")
            bash_no_raise("sudo apt-get clean")

        if docker_images:
            print("Pruning Docker images")
            bash_no_raise("sudo docker image prune --all --force")

        if swap_storage:
            print("Removing swap")
            bash_no_raise("sudo swapoff -a")
            bash_no_raise("sudo rm -f /mnt/swapfile")

    bash("df -h")


def _remove_paths(paths: list[str], sudo: bool = False) -> None:
    existing = [path for path in paths if Path(path).exists()]
    if not existing:
        return
    if sudo:
        bash_no_raise(f"sudo rm -rf {shlex.join(existing)}")
    elif platform.system() == "Windows":
        for path in existing:
            shutil.rmtree(path, ignore_errors=True)
    else:
        bash_no_raise(f"rm -rf {shlex.join(existing)}")
