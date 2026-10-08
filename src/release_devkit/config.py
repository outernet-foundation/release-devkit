from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings
from strictyaml import load as load_strict_yaml

DEFAULT_CONFIG_PATH = Path("release-devkit.yaml")
KNOWN_REGISTRIES = frozenset({"nuget", "npm", "pypi"})


class Settings(BaseSettings):
    github_token: str = ""
    nuget_api_key: str = ""
    github_repository: str = ""
    github_actor: str = ""
    github_workspace: str = ""
    github_ref: str = ""

    @model_validator(mode="after")
    def require_runner_environment(self) -> Self:
        missing = [
            env_var
            for env_var, value in (
                ("GITHUB_REPOSITORY", self.github_repository),
                ("GITHUB_ACTOR", self.github_actor),
                ("GITHUB_WORKSPACE", self.github_workspace),
            )
            if not value
        ]
        if missing:
            raise SystemExit(f"{', '.join(missing)} not set — these verbs read the GitHub runner environment")
        return self


class PackageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path
    major_minor: str = Field(pattern=r"^\d+\.\d+$")
    registry: str
    identity: str


class BuildArtifactConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    platform: str
    file: str


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path
    major_minor: str = Field(pattern=r"^\d+\.\d+$")
    builds: list[BuildArtifactConfig] = Field(min_length=1)


class PublishConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packages: dict[str, PackageConfig] = Field(default_factory=dict)
    apps: dict[str, AppConfig] = Field(default_factory=dict)
    built_images: bool = False

    @model_validator(mode="after")
    def validate_registry_names(self) -> "PublishConfig":
        for name, package in self.packages.items():
            if package.registry not in KNOWN_REGISTRIES:
                raise ValueError(f"package '{name}' declares unknown registry '{package.registry}'")
        return self


def load_config(path: Path) -> PublishConfig:
    data = load_strict_yaml(path.read_text(encoding="utf-8")).data
    return PublishConfig.model_validate(data if data else {})
