import json
from pathlib import Path
from subprocess import CalledProcessError

import pytest

from release_devkit.registries import NpmRegistry, NuGetRegistry, PublishRequest
from release_devkit.registries import (
    DEV_VERSION_FORMATS,
    KNOWN_REGISTRIES,
    ephemeral_manifest_patch,
    ephemeral_pyproject_patch,
    nuget_injection_properties,
    patch_project_dependencies,
    patch_project_version,
    pep440_dev_version,
    semver_dev_version,
)

PYPROJECT = (
    "[project]\n"
    'name = "example"\n'
    'version = "0.0.0.dev0"\n'
    'dependencies = ["pydantic>=2"]\n'
    "\n"
    "[tool.hatch.version]\n"
    'version = "not-this-one"\n'
    "\n"
    "[build-system]\n"
    'requires = ["hatchling"]\n'
)

PYPROJECT_WITH_SENTINELS = (
    "[project]\n"
    'name = "example"\n'
    'version = "0.0.0.dev0"\n'
    "dependencies = [\n"
    '    "sibling==0.0.0+local",\n'
    '    "pydantic>=2",\n'
    "]\n"
    "\n"
    "[tool.uv.sources]\n"
    "sibling = { workspace = true }\n"
)


class CommandRecorder:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def __call__(
        self,
        command: str,
        *,
        cwd: Path | None = None,
        stdin_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        self.commands.append(command)
        return ""


def write_manifest(tmp_path: Path) -> Path:
    manifest_path = tmp_path / "package.json"
    manifest_path.write_text(
        json.dumps({
            "name": "org.outernet.placeframe",
            "version": "0.0.0-local",
            "dependencies": {"org.outernet.placeframe.apiclient": "0.0.0+local"},
        }),
        encoding="utf-8",
    )
    return manifest_path


def test_patch_updates_version_and_pins_then_restores(tmp_path: Path):
    manifest_path = write_manifest(tmp_path)

    with ephemeral_manifest_patch(tmp_path, "0.2.1", {"org.outernet.placeframe.apiclient": "0.1.8"}):
        patched = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert patched["version"] == "0.2.1"
        assert patched["dependencies"] == {"org.outernet.placeframe.apiclient": "0.1.8"}

    restored = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert restored["version"] == "0.0.0-local"
    assert restored["dependencies"] == {"org.outernet.placeframe.apiclient": "0.0.0+local"}


def test_patch_skips_dependency_keys_absent_from_the_manifest(tmp_path: Path):
    manifest_path = write_manifest(tmp_path)

    with ephemeral_manifest_patch(tmp_path, "0.2.1", {"some.pypi.sibling": "0.3.0"}):
        patched = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert patched["dependencies"] == {"org.outernet.placeframe.apiclient": "0.0.0+local"}


def test_patch_restores_on_error(tmp_path: Path):
    manifest_path = write_manifest(tmp_path)
    original = manifest_path.read_text(encoding="utf-8")

    with pytest.raises(RuntimeError), ephemeral_manifest_patch(tmp_path, "0.2.1", {}):
        raise RuntimeError("publish exploded")

    assert manifest_path.read_text(encoding="utf-8") == original


def test_patch_project_version_replaces_the_project_table_version() -> None:
    patched = patch_project_version(PYPROJECT, "0.1.3")
    assert 'version = "0.1.3"\n' in patched
    assert 'version = "0.0.0.dev0"' not in patched
    assert 'version = "not-this-one"' in patched


def test_patch_project_version_raises_without_a_project_version() -> None:
    without_version = '[project]\nname = "example"\n\n[build-system]\nrequires = ["hatchling"]\n'
    with pytest.raises(ValueError, match="no \\[project\\] version"):
        patch_project_version(without_version, "0.1.3")


def test_ephemeral_pyproject_patch_restores_the_original(tmp_path: Path) -> None:
    manifest_path = tmp_path / "pyproject.toml"
    manifest_path.write_text(PYPROJECT, encoding="utf-8")

    with ephemeral_pyproject_patch(tmp_path, "0.2.0", {}):
        assert 'version = "0.2.0"' in manifest_path.read_text(encoding="utf-8")

    assert manifest_path.read_text(encoding="utf-8") == PYPROJECT


def test_ephemeral_pyproject_patch_restores_on_error(tmp_path: Path) -> None:
    manifest_path = tmp_path / "pyproject.toml"
    manifest_path.write_text(PYPROJECT, encoding="utf-8")

    with pytest.raises(RuntimeError), ephemeral_pyproject_patch(tmp_path, "0.2.0", {}):
        raise RuntimeError("publish exploded")

    assert manifest_path.read_text(encoding="utf-8") == PYPROJECT


def test_ephemeral_pyproject_patch_rewrites_sentinel_specifiers(tmp_path: Path) -> None:
    manifest_path = tmp_path / "pyproject.toml"
    manifest_path.write_text(PYPROJECT_WITH_SENTINELS, encoding="utf-8")

    with ephemeral_pyproject_patch(tmp_path, "0.2.0", {"sibling": "1.0.4"}):
        patched = manifest_path.read_text(encoding="utf-8")
        assert 'version = "0.2.0"' in patched
        assert '"sibling==1.0.4"' in patched
        assert "0.0.0+local" not in patched
        assert '"pydantic>=2"' in patched

    assert manifest_path.read_text(encoding="utf-8") == PYPROJECT_WITH_SENTINELS


def test_patch_project_dependencies_leaves_absent_entries_alone() -> None:
    patched = patch_project_dependencies(PYPROJECT_WITH_SENTINELS, {"elsewhere": "9.9.9"})

    assert patched == PYPROJECT_WITH_SENTINELS


def test_dev_version_spellings_per_registry() -> None:
    assert semver_dev_version("0.1.8", "123456") == "0.1.8-dev.123456"
    assert pep440_dev_version("0.1.8", "123456") == "0.1.8.dev123456"


def test_dev_version_formats_cover_every_known_registry() -> None:
    assert set(DEV_VERSION_FORMATS) == KNOWN_REGISTRIES


def test_npm_publish_rides_the_dev_dist_tag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = write_manifest(tmp_path)
    recorder = CommandRecorder()
    monkeypatch.setattr("release_devkit.registries.bash_output", recorder)

    NpmRegistry().publish(
        PublishRequest(
            path=tmp_path,
            identity="org.outernet.placeframe",
            version="0.2.1-dev.42",
            dependency_versions={},
            dist_tag="dev",
        )
    )

    assert recorder.commands == ["npm publish --access public --provenance --loglevel verbose --tag dev"]
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["version"] == "0.0.0-local"


def test_npm_publish_without_dist_tag_leaves_latest_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_manifest(tmp_path)
    recorder = CommandRecorder()
    monkeypatch.setattr("release_devkit.registries.bash_output", recorder)

    NpmRegistry().publish(
        PublishRequest(path=tmp_path, identity="org.outernet.placeframe", version="0.2.1", dependency_versions={})
    )

    assert recorder.commands == ["npm publish --access public --provenance --loglevel verbose"]


class ConflictingCommand:
    def __init__(self, stderr: str) -> None:
        self.stderr = stderr

    def __call__(
        self,
        command: str,
        *,
        cwd: Path | None = None,
        stdin_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        raise CalledProcessError(returncode=1, cmd=command, stderr=self.stderr)


def test_npm_publish_swallows_version_conflict_from_current_npm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_manifest(tmp_path)
    monkeypatch.setattr(
        "release_devkit.registries.bash_output",
        ConflictingCommand("npm error You cannot publish over the previously published versions: 0.2.1.\n"),
    )

    NpmRegistry().publish(
        PublishRequest(path=tmp_path, identity="org.outernet.placeframe", version="0.2.1", dependency_versions={})
    )


def test_npm_publish_swallows_version_conflict_from_legacy_npm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_manifest(tmp_path)
    monkeypatch.setattr(
        "release_devkit.registries.bash_output",
        ConflictingCommand("npm ERR! code EPUBLISHCONFLICT\nnpm ERR! cannot publish over existing version\n"),
    )

    NpmRegistry().publish(
        PublishRequest(path=tmp_path, identity="org.outernet.placeframe", version="0.2.1", dependency_versions={})
    )


def test_npm_publish_rides_through_on_unrelated_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_manifest(tmp_path)
    monkeypatch.setattr(
        "release_devkit.registries.bash_output",
        ConflictingCommand("npm error code ENEEDAUTH\nnpm error need auth to publish\n"),
    )

    with pytest.raises(CalledProcessError):
        NpmRegistry().publish(
            PublishRequest(path=tmp_path, identity="org.outernet.placeframe", version="0.2.1", dependency_versions={})
        )


NUGET_CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.1</TargetFramework>
    <SiblingVersion>0.0.0+local</SiblingVersion>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="External.Lib" Version="4.2.0" />
    <PackageReference Include="Org.Sibling" Version="$(SiblingVersion)" />
  </ItemGroup>
</Project>
"""


def write_nuget_project(tmp_path: Path) -> None:
    (tmp_path / "Consumer.csproj").write_text(NUGET_CSPROJ, encoding="utf-8")


def test_nuget_publish_injects_property_flags_beside_the_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nuget_project(tmp_path)
    recorder = CommandRecorder()
    monkeypatch.setattr("release_devkit.registries.bash", recorder)

    NuGetRegistry("key").publish(
        PublishRequest(
            path=tmp_path,
            identity="Org.Consumer",
            version="1.0.6",
            dependency_versions={"Org.Sibling": "1.0.6"},
        )
    )

    assert recorder.commands[0].startswith("dotnet pack -c Release -p:Version=1.0.6 -p:SiblingVersion=1.0.6 -o ")


def test_nuget_publish_without_dependencies_omits_property_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nuget_project(tmp_path)
    recorder = CommandRecorder()
    monkeypatch.setattr("release_devkit.registries.bash", recorder)

    NuGetRegistry("key").publish(
        PublishRequest(path=tmp_path, identity="Org.Consumer", version="1.0.6", dependency_versions={})
    )

    assert recorder.commands[0].startswith("dotnet pack -c Release -p:Version=1.0.6 -o ")


def test_nuget_publish_writes_the_nupkg_outside_the_package_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nuget_project(tmp_path)
    recorder = CommandRecorder()
    monkeypatch.setattr("release_devkit.registries.bash", recorder)

    NuGetRegistry("key").publish(
        PublishRequest(path=tmp_path, identity="Org.Consumer", version="1.0.6", dependency_versions={})
    )

    pack_command, push_command = recorder.commands
    outdir = pack_command.rsplit(" -o ", 1)[1]
    assert not Path(outdir).is_relative_to(tmp_path)
    assert outdir in push_command


def test_nuget_injection_properties_without_matching_reference_is_loud(tmp_path: Path) -> None:
    write_nuget_project(tmp_path)

    with pytest.raises(ValueError, match=r"no PackageReference found for \['Org.Missing'\]"):
        nuget_injection_properties(tmp_path, {"Org.Missing": "1.0.0"})


def test_nuget_injection_properties_literal_version_is_loud(tmp_path: Path) -> None:
    csproj = NUGET_CSPROJ.replace('Version="$(SiblingVersion)"', 'Version="1.0.0"')
    (tmp_path / "Consumer.csproj").write_text(csproj, encoding="utf-8")

    with pytest.raises(ValueError, match=r"carries literal version '1.0.0'"):
        nuget_injection_properties(tmp_path, {"Org.Sibling": "1.0.6"})


def test_nuget_push_failure_never_leaks_the_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_nuget_project(tmp_path)

    def failing_push(
        command: str,
        *,
        cwd: Path | None = None,
        stdin_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        if "nuget push" in command:
            raise CalledProcessError(
                returncode=1, cmd=command, stderr="Response status code does not indicate success: 401\nsecond line\n"
            )
        return ""

    monkeypatch.setattr("release_devkit.registries.bash", failing_push)

    with pytest.raises(SystemExit) as excinfo:
        NuGetRegistry("SECRET-KEY").publish(
            PublishRequest(path=tmp_path, identity="Org.Consumer", version="1.0.6", dependency_versions={})
        )

    message = str(excinfo.value)
    assert "exit 1" in message
    assert "Response status code does not indicate success: 401" in message
    assert "SECRET-KEY" not in message
    assert "--api-key" not in message


def test_nuget_push_failure_without_stderr_still_names_the_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nuget_project(tmp_path)

    def failing_push(
        command: str,
        *,
        cwd: Path | None = None,
        stdin_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        if "nuget push" in command:
            raise CalledProcessError(returncode=2, cmd=command, stderr=None)
        return ""

    monkeypatch.setattr("release_devkit.registries.bash", failing_push)

    with pytest.raises(SystemExit, match=r"dotnet nuget push failed \(exit 2\): no stderr output"):
        NuGetRegistry("key").publish(
            PublishRequest(path=tmp_path, identity="Org.Consumer", version="1.0.6", dependency_versions={})
        )
