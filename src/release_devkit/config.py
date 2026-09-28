from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .registries import KNOWN_REGISTRIES


class PackageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: Path
    major_minor: str = Field(pattern=r"^\d+\.\d+$")
    registries: dict[str, str] = Field(default_factory=dict)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: Path
    major_minor: str = Field(pattern=r"^\d+\.\d+$")
    tag_prefix: str
    display_name: str


class PublishConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packages: list[PackageConfig] = Field(default_factory=list)
    apps: list[AppConfig] = Field(default_factory=list)
    ci_workflow: str

    @model_validator(mode="after")
    def validate_unique_package_names(self) -> "PublishConfig":
        seen: set[str] = set()
        for package in self.packages:
            if package.name in seen:
                raise ValueError(f"duplicate package name '{package.name}'")
            seen.add(package.name)
        return self

    @model_validator(mode="after")
    def validate_registry_names(self) -> "PublishConfig":
        for package in self.packages:
            unknown_registries = set(package.registries) - KNOWN_REGISTRIES
            if unknown_registries:
                raise ValueError(f"package '{package.name}' declares unknown registries: {sorted(unknown_registries)}")
        return self


def load_config(path: Path) -> PublishConfig:
    return PublishConfig.model_validate_json(path.read_text(encoding="utf-8"))


def select_packages(packages: list[PackageConfig], only: Sequence[str], exclude: Sequence[str]) -> list[PackageConfig]:
    if only and exclude:
        raise SystemExit("--only and --exclude are mutually exclusive")
    names = [package.name for package in packages]
    for requested in [*only, *exclude]:
        if requested not in names:
            raise SystemExit(f"Unknown package '{requested}'. Valid: {', '.join(names)}")
    if only:
        selected = set(only)
        return [package for package in packages if package.name in selected]
    if exclude:
        deselected = set(exclude)
        return [package for package in packages if package.name not in deselected]
    return packages
