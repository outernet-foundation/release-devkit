from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from strictyaml import load as load_strict_yaml

from .registries import KNOWN_REGISTRIES

DEFAULT_CONFIG_PATH = Path("release-devkit.yaml")


class PackageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path
    major_minor: str = Field(pattern=r"^\d+\.\d+$")
    registries: dict[str, str] = Field(default_factory=dict)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path
    major_minor: str = Field(pattern=r"^\d+\.\d+$")


class PublishConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packages: dict[str, PackageConfig] = Field(default_factory=dict)
    apps: dict[str, AppConfig] = Field(default_factory=dict)
    ci_workflow: str

    @model_validator(mode="after")
    def validate_registry_names(self) -> "PublishConfig":
        for name, package in self.packages.items():
            unknown_registries = set(package.registries) - KNOWN_REGISTRIES
            if unknown_registries:
                raise ValueError(f"package '{name}' declares unknown registries: {sorted(unknown_registries)}")
        return self


def load_config(path: Path) -> PublishConfig:
    return PublishConfig.model_validate(load_strict_yaml(path.read_text(encoding="utf-8")).data)


def select_packages(
    packages: dict[str, PackageConfig], only: Sequence[str], exclude: Sequence[str]
) -> dict[str, PackageConfig]:
    if only and exclude:
        raise SystemExit("--only and --exclude are mutually exclusive")
    names = list(packages)
    for requested in [*only, *exclude]:
        if requested not in names:
            raise SystemExit(f"Unknown package '{requested}'. Valid: {', '.join(names)}")
    if only:
        selected = set(only)
        return {name: package for name, package in packages.items() if name in selected}
    if exclude:
        deselected = set(exclude)
        return {name: package for name, package in packages.items() if name not in deselected}
    return packages
