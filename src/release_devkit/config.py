from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings
from strictyaml import load as load_strict_yaml

from release_devkit.registries import KNOWN_REGISTRIES

DEFAULT_CONFIG_PATH = Path("release-devkit.yaml")


class Settings(BaseSettings):
    github_token: str = ""
    nuget_api_key: str = ""


class PackageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path
    major_minor: str = Field(pattern=r"^\d+\.\d+$")
    registries: dict[str, str] = Field(default_factory=dict)


class BuildArtifactConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    platform: str
    file: str | None = None
    name: str | None = None


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path
    major_minor: str = Field(pattern=r"^\d+\.\d+$")
    builds: list[BuildArtifactConfig] | None = Field(default=None, min_length=1)


class PublishConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packages: dict[str, PackageConfig] = Field(default_factory=dict)
    apps: dict[str, AppConfig] = Field(default_factory=dict)
    builds_registry: str | None = None
    ci_workflow: str

    @model_validator(mode="after")
    def validate_registry_names(self) -> "PublishConfig":
        for name, package in self.packages.items():
            unknown_registries = set(package.registries) - KNOWN_REGISTRIES
            if unknown_registries:
                raise ValueError(f"package '{name}' declares unknown registries: {sorted(unknown_registries)}")
        if self.builds_registry is None and any(app.builds for app in self.apps.values()):
            raise ValueError("builds_registry is required when any app declares builds")
        return self


def load_config(path: Path) -> PublishConfig:
    return PublishConfig.model_validate(load_strict_yaml(path.read_text(encoding="utf-8")).data)


def write_step_summary(path: str | None, text: str) -> None:
    if path:
        with Path(path).open("a", encoding="utf-8") as file:
            file.write(text + "\n")
