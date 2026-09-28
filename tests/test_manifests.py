import json
from pathlib import Path

import pytest
from bashrun.bash import bash

from release_devkit.config import PackageConfig
from release_devkit.manifests import resolve_edges
from release_devkit.registries import SENTINEL_VERSION


def npm_package(name: str, identity: str) -> PackageConfig:
    return PackageConfig(path=Path(name), major_minor="1.0", registries={"npm": identity})


def nuget_package(name: str, identity: str) -> PackageConfig:
    return PackageConfig(path=Path(name), major_minor="1.0", registries={"nuget": identity})


def write_npm_manifest(root: Path, package_name: str, dependencies: dict[str, str]) -> None:
    package_dir = root / package_name
    package_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"name": package_name, "version": "0.0.0-local", "dependencies": dependencies}
    (package_dir / "package.json").write_text(json.dumps(manifest), encoding="utf-8")


def write_pypi_manifest(root: Path, package_name: str, dependencies: list[str]) -> None:
    package_dir = root / package_name
    package_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "[project]",
        f'name = "{package_name}"',
        'version = "0.0.0.dev0"',
        "dependencies = [",
        *(f'    "{dependency}",' for dependency in dependencies),
        "]",
    ]
    (package_dir / "pyproject.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def pypi_package(name: str) -> PackageConfig:
    return PackageConfig(path=Path(name), major_minor="0.1", registries={"pypi": name})


NUGET_LIBRARY_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.1</TargetFramework>
  </PropertyGroup>
</Project>
"""

NUGET_CONSUMER_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.1</TargetFramework>
    <SiblingVersion>{sibling_default}</SiblingVersion>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="External.Lib" Version="4.2.0" />
    <PackageReference Include="Org.Sibling" Version="$(SiblingVersion)" />
  </ItemGroup>
</Project>
"""


def write_nuget_library(root: Path, package_name: str) -> None:
    package_dir = root / package_name / "src"
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "Library.csproj").write_text(NUGET_LIBRARY_CSPROJ, encoding="utf-8")


def write_nuget_consumer(root: Path, package_name: str, sibling_default: str) -> None:
    package_dir = root / package_name / "src"
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "Consumer.csproj").write_text(
        NUGET_CONSUMER_CSPROJ.format(sibling_default=sibling_default), encoding="utf-8"
    )


def test_npm_sentinel_dependency_forms_edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_npm_manifest(tmp_path, "core", {})
    write_npm_manifest(tmp_path, "arfoundation", {"org.example.core": SENTINEL_VERSION, "com.unity.xr": "6.0.5"})
    packages = {
        "core": npm_package("core", "org.example.core"),
        "arfoundation": npm_package("arfoundation", "org.example.arfoundation"),
    }

    edges = resolve_edges(packages)

    assert edges["core"] == []
    assert len(edges["arfoundation"]) == 1
    edge = edges["arfoundation"][0]
    assert edge.dependency_package == "core"
    assert edge.registry == "npm"
    assert edge.identity == "org.example.core"
    assert edge.property_name is None


def test_npm_real_version_on_config_identity_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_npm_manifest(tmp_path, "core", {})
    write_npm_manifest(tmp_path, "arfoundation", {"org.example.core": "1.0.6-dev.35815669170"})
    packages = {
        "core": npm_package("core", "org.example.core"),
        "arfoundation": npm_package("arfoundation", "org.example.arfoundation"),
    }

    with pytest.raises(ValueError, match="must be authored as the sentinel"):
        resolve_edges(packages)


def test_npm_sentinel_on_non_config_identity_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_npm_manifest(tmp_path, "arfoundation", {"com.fofx.stateful": SENTINEL_VERSION})
    packages = {"arfoundation": npm_package("arfoundation", "org.example.arfoundation")}

    with pytest.raises(ValueError, match=r"no config package owns that npm identity"):
        resolve_edges(packages)


def test_npm_missing_manifest_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "arfoundation").mkdir()
    packages = {"arfoundation": npm_package("arfoundation", "org.example.arfoundation")}

    with pytest.raises(ValueError, match=r"no package.json under 'arfoundation'"):
        resolve_edges(packages)


def test_npm_malformed_dependencies_table_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    package_dir = tmp_path / "arfoundation"
    package_dir.mkdir()
    (package_dir / "package.json").write_text(
        '{"name": "x", "version": "0.0.0-local", "dependencies": []}', encoding="utf-8"
    )
    packages = {"arfoundation": npm_package("arfoundation", "org.example.arfoundation")}

    with pytest.raises(Exception, match="dependencies"):
        resolve_edges(packages)


def test_pypi_sentinel_dependency_forms_edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_pypi_manifest(tmp_path, "sibling", [])
    write_pypi_manifest(tmp_path, "consumer", [f"sibling=={SENTINEL_VERSION}", "pydantic>=2"])
    packages = {"sibling": pypi_package("sibling"), "consumer": pypi_package("consumer")}

    edges = resolve_edges(packages)

    assert len(edges["consumer"]) == 1
    assert edges["consumer"][0].dependency_package == "sibling"
    assert edges["consumer"][0].identity == "sibling"


def test_pypi_real_version_on_config_identity_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_pypi_manifest(tmp_path, "sibling", [])
    write_pypi_manifest(tmp_path, "consumer", ["sibling==1.2.3"])
    packages = {"sibling": pypi_package("sibling"), "consumer": pypi_package("consumer")}

    with pytest.raises(ValueError, match="must be authored as the sentinel"):
        resolve_edges(packages)


def test_pypi_sentinel_on_non_config_identity_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_pypi_manifest(tmp_path, "consumer", [f"leftalone=={SENTINEL_VERSION}"])
    packages = {"consumer": pypi_package("consumer")}

    with pytest.raises(ValueError, match=r"no config package owns that pypi identity"):
        resolve_edges(packages)


def test_pypi_missing_manifest_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "consumer").mkdir()
    packages = {"consumer": pypi_package("consumer")}

    with pytest.raises(ValueError, match=r"no pyproject.toml under 'consumer'"):
        resolve_edges(packages)


def test_pypi_project_without_dependencies_table_yields_no_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    package_dir = tmp_path / "consumer"
    package_dir.mkdir()
    (package_dir / "pyproject.toml").write_text('[project]\nname = "consumer"\n', encoding="utf-8")
    packages = {"consumer": pypi_package("consumer")}

    assert resolve_edges(packages) == {"consumer": []}


def test_nuget_property_sentinel_forms_edge_with_property_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_nuget_library(tmp_path, "sibling")
    write_nuget_consumer(tmp_path, "consumer", SENTINEL_VERSION)
    packages = {
        "sibling": nuget_package("sibling", "Org.Sibling"),
        "consumer": nuget_package("consumer", "Org.Consumer"),
    }

    edges = resolve_edges(packages)

    assert edges["sibling"] == []
    assert len(edges["consumer"]) == 1
    edge = edges["consumer"][0]
    assert edge.dependency_package == "sibling"
    assert edge.registry == "nuget"
    assert edge.identity == "Org.Sibling"
    assert edge.property_name == "SiblingVersion"


def test_nuget_non_sentinel_property_default_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_nuget_library(tmp_path, "sibling")
    write_nuget_consumer(tmp_path, "consumer", "1.0.0")
    packages = {
        "sibling": nuget_package("sibling", "Org.Sibling"),
        "consumer": nuget_package("consumer", "Org.Consumer"),
    }

    with pytest.raises(ValueError, match="must be authored as the sentinel"):
        resolve_edges(packages)


def test_nuget_literal_version_on_config_identity_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_nuget_library(tmp_path, "sibling")
    csproj = NUGET_CONSUMER_CSPROJ.format(sibling_default=SENTINEL_VERSION).replace(
        'Version="$(SiblingVersion)"', 'Version="1.0.0"'
    )
    package_dir = tmp_path / "consumer" / "src"
    package_dir.mkdir(parents=True)
    (package_dir / "Consumer.csproj").write_text(csproj, encoding="utf-8")
    packages = {
        "sibling": nuget_package("sibling", "Org.Sibling"),
        "consumer": nuget_package("consumer", "Org.Consumer"),
    }

    with pytest.raises(ValueError, match="must be authored as the sentinel"):
        resolve_edges(packages)


def test_nuget_property_without_default_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_nuget_library(tmp_path, "sibling")
    csproj = NUGET_CONSUMER_CSPROJ.format(sibling_default=SENTINEL_VERSION).replace(
        f"    <SiblingVersion>{SENTINEL_VERSION}</SiblingVersion>\n", ""
    )
    package_dir = tmp_path / "consumer" / "src"
    package_dir.mkdir(parents=True)
    (package_dir / "Consumer.csproj").write_text(csproj, encoding="utf-8")
    packages = {
        "sibling": nuget_package("sibling", "Org.Sibling"),
        "consumer": nuget_package("consumer", "Org.Consumer"),
    }

    with pytest.raises(ValueError, match="carries no default"):
        resolve_edges(packages)


def test_nuget_literal_sentinel_on_external_identity_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    csproj = NUGET_CONSUMER_CSPROJ.format(sibling_default=SENTINEL_VERSION).replace(
        '<PackageReference Include="External.Lib" Version="4.2.0" />',
        f'<PackageReference Include="External.Lib" Version="{SENTINEL_VERSION}" />',
    )
    package_dir = tmp_path / "consumer" / "src"
    package_dir.mkdir(parents=True)
    (package_dir / "Consumer.csproj").write_text(csproj, encoding="utf-8")
    packages = {"consumer": nuget_package("consumer", "Org.Consumer")}

    with pytest.raises(ValueError, match=r"no config package owns that nuget identity"):
        resolve_edges(packages)


def test_nuget_missing_csproj_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "consumer").mkdir()
    packages = {"consumer": nuget_package("consumer", "Org.Consumer")}

    with pytest.raises(ValueError, match=r"no csproj under 'consumer'"):
        resolve_edges(packages)


def test_identity_resolution_is_scoped_per_registry_kind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_npm_manifest(tmp_path, "npm-pkg", {})
    write_pypi_manifest(tmp_path, "pypi-pkg", ["npm-pkg>=1.0"])
    packages = {
        "npm-pkg": PackageConfig(path=Path("npm-pkg"), major_minor="1.0", registries={"npm": "npm-pkg"}),
        "pypi-pkg": PackageConfig(path=Path("pypi-pkg"), major_minor="0.1", registries={"pypi": "pypi-pkg"}),
    }

    edges = resolve_edges(packages)

    assert edges["pypi-pkg"] == []


def test_multi_registry_package_unions_edges_across_manifests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_npm_manifest(tmp_path, "npm-sibling", {})
    write_pypi_manifest(tmp_path, "pypi-sibling", [])
    write_npm_manifest(tmp_path, "dual", {"org.example.npm-sibling": SENTINEL_VERSION})
    write_pypi_manifest(tmp_path, "dual", [f"pypi-sibling=={SENTINEL_VERSION}"])
    packages = {
        "npm-sibling": PackageConfig(
            path=Path("npm-sibling"),
            major_minor="1.0",
            registries={"npm": "org.example.npm-sibling"},
        ),
        "pypi-sibling": pypi_package("pypi-sibling"),
        "dual": PackageConfig(
            path=Path("dual"), major_minor="1.0", registries={"npm": "org.example.dual", "pypi": "dual"}
        ),
    }

    edges = resolve_edges(packages)

    assert {edge.dependency_package for edge in edges["dual"]} == {"npm-sibling", "pypi-sibling"}
    assert {edge.identity for edge in edges["dual"]} == {"org.example.npm-sibling", "pypi-sibling"}


def test_duplicate_identity_across_packages_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_npm_manifest(tmp_path, "one", {})
    write_npm_manifest(tmp_path, "two", {})
    packages = {
        "one": npm_package("one", "org.example.dup"),
        "two": npm_package("two", "org.example.dup"),
    }

    with pytest.raises(ValueError, match=r"share npm identity 'org.example.dup'"):
        resolve_edges(packages)


def test_uv_accepts_sentinel_specifiers_with_workspace_sources(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    sibling = consumer / "sibling"
    sibling.mkdir(parents=True)
    (consumer / "pyproject.toml").write_text(
        "[project]\n"
        'name = "consumer"\n'
        'version = "0.0.0.dev0"\n'
        'requires-python = ">=3.13"\n'
        "dependencies = [\n"
        f'    "sibling=={SENTINEL_VERSION}",\n'
        "]\n"
        "\n"
        "[tool.uv.sources]\n"
        "sibling = { workspace = true }\n"
        "\n"
        "[tool.uv.workspace]\n"
        'members = ["sibling"]\n'
        "\n"
        "[build-system]\n"
        'requires = ["hatchling"]\n'
        'build-backend = "hatchling.build"\n',
        encoding="utf-8",
    )
    (sibling / "pyproject.toml").write_text(
        "[project]\n"
        'name = "sibling"\n'
        'version = "0.0.0.dev0"\n'
        'requires-python = ">=3.13"\n'
        "dependencies = []\n"
        "\n"
        "[build-system]\n"
        'requires = ["hatchling"]\n'
        'build-backend = "hatchling.build"\n',
        encoding="utf-8",
    )

    bash("uv lock --offline", cwd=consumer)

    assert (consumer / "uv.lock").is_file()
