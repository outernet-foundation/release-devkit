import json
from pathlib import Path
from subprocess import CalledProcessError

import pytest

from release_devkit.publishing import NpmRegistry, NuGetRegistry, ResolvedDependency
from release_devkit.publishing import (
    ephemeral_manifest_patch,
    ephemeral_pyproject_patch,
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


def test_npm_publish_rides_the_dev_dist_tag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = write_manifest(tmp_path)
    recorder = CommandRecorder()
    monkeypatch.setattr("release_devkit.publishing.bash_output", recorder)

    NpmRegistry().publish(
        path=tmp_path,
        base_version="0.2.1",
        resolved_dependencies={},
        dev=True,
        short_sha="42",
    )

    assert recorder.commands == ["npm publish --access public --provenance --loglevel verbose --tag dev"]
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["version"] == "0.0.0-local"


def test_npm_publish_without_dist_tag_leaves_latest_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_manifest(tmp_path)
    recorder = CommandRecorder()
    monkeypatch.setattr("release_devkit.publishing.bash_output", recorder)

    NpmRegistry().publish(tmp_path, "0.2.1", {}, False, "")

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
        "release_devkit.publishing.bash_output",
        ConflictingCommand("npm error You cannot publish over the previously published versions: 0.2.1.\n"),
    )

    NpmRegistry().publish(tmp_path, "0.2.1", {}, False, "")


def test_npm_publish_swallows_version_conflict_from_legacy_npm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_manifest(tmp_path)
    monkeypatch.setattr(
        "release_devkit.publishing.bash_output",
        ConflictingCommand("npm ERR! code EPUBLISHCONFLICT\nnpm ERR! cannot publish over existing version\n"),
    )

    NpmRegistry().publish(tmp_path, "0.2.1", {}, False, "")


def test_npm_publish_rides_through_on_unrelated_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_manifest(tmp_path)
    monkeypatch.setattr(
        "release_devkit.publishing.bash_output",
        ConflictingCommand("npm error code ENEEDAUTH\nnpm error need auth to publish\n"),
    )

    with pytest.raises(CalledProcessError):
        NpmRegistry().publish(tmp_path, "0.2.1", {}, False, "")


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
    monkeypatch.setattr("release_devkit.publishing.bash", recorder)

    NuGetRegistry("key").publish(
        path=tmp_path,
        base_version="1.0.6",
        resolved_dependencies={"Org.Sibling": ResolvedDependency(version="1.0.6", co_publishing=True)},
        dev=False,
        short_sha="",
    )

    assert recorder.commands[0].startswith("dotnet pack -c Release -p:Version=1.0.6 -p:SiblingVersion=1.0.6 -o ")


def test_nuget_publish_without_dependencies_omits_property_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nuget_project(tmp_path)
    recorder = CommandRecorder()
    monkeypatch.setattr("release_devkit.publishing.bash", recorder)

    NuGetRegistry("key").publish(tmp_path, "1.0.6", {}, False, "")

    assert recorder.commands[0].startswith("dotnet pack -c Release -p:Version=1.0.6 -o ")


def test_nuget_publish_writes_the_nupkg_outside_the_package_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_nuget_project(tmp_path)
    recorder = CommandRecorder()
    monkeypatch.setattr("release_devkit.publishing.bash", recorder)

    NuGetRegistry("key").publish(tmp_path, "1.0.6", {}, False, "")

    pack_command, push_command = recorder.commands
    outdir = pack_command.rsplit(" -o ", 1)[1]
    assert not Path(outdir).is_relative_to(tmp_path)
    assert outdir in push_command


def test_nuget_publish_without_matching_reference_is_loud(tmp_path: Path) -> None:
    write_nuget_project(tmp_path)

    with pytest.raises(ValueError, match=r"no PackageReference found for \['Org.Missing'\]"):
        NuGetRegistry("key").publish(
            path=tmp_path,
            base_version="1.0.6",
            resolved_dependencies={"Org.Missing": ResolvedDependency(version="1.0.0", co_publishing=True)},
            dev=False,
            short_sha="",
        )


def test_nuget_publish_with_literal_version_is_loud(tmp_path: Path) -> None:
    csproj = NUGET_CSPROJ.replace('Version="$(SiblingVersion)"', 'Version="1.0.0"')
    (tmp_path / "Consumer.csproj").write_text(csproj, encoding="utf-8")

    with pytest.raises(ValueError, match=r"carries literal version '1.0.0'"):
        NuGetRegistry("key").publish(
            path=tmp_path,
            base_version="1.0.6",
            resolved_dependencies={"Org.Sibling": ResolvedDependency(version="1.0.6", co_publishing=True)},
            dev=False,
            short_sha="",
        )


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

    monkeypatch.setattr("release_devkit.publishing.bash", failing_push)

    with pytest.raises(SystemExit) as excinfo:
        NuGetRegistry("SECRET-KEY").publish(tmp_path, "1.0.6", {}, False, "")

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

    monkeypatch.setattr("release_devkit.publishing.bash", failing_push)

    with pytest.raises(SystemExit, match=r"dotnet nuget push failed \(exit 2\): no stderr output"):
        NuGetRegistry("key").publish(tmp_path, "1.0.6", {}, False, "")
