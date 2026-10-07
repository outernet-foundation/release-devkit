import json
from pathlib import Path

import pytest

from release_devkit import plan as plan_module
from release_devkit.config import AppConfig, PackageConfig, PublishConfig
from release_devkit.manifests import DependencyEdge
from release_devkit.plan import (
    PackagePlan,
    ResolvedDependency,
    compute_release_plan,
    next_version,
    package_rows,
    resolve_dependency_versions,
)
from release_devkit.registries import SENTINEL_VERSION
from release_devkit.tags import latest_version, latest_version_in_line, parse_major_minor, parse_version


def test_latest_version_skips_prerelease_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "release_devkit.tags.list_tag_versions",
        preview_and_stable_tags,
    )

    assert latest_version("pkg-v") == "1.0.5"


def test_latest_version_returns_none_when_no_stable_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "release_devkit.tags.list_tag_versions",
        prerelease_only_tags,
    )

    assert latest_version("pkg-v") is None


def test_latest_version_in_line_filters_to_declared_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "release_devkit.tags.list_tag_versions",
        multi_line_tags,
    )

    assert latest_version_in_line("pkg-v", "1.0") == "1.0.10"
    assert latest_version_in_line("pkg-v", "1.9") == "1.9.2"
    assert latest_version_in_line("pkg-v", "2.4") == "2.4.1"
    assert latest_version_in_line("pkg-v", "1.10") == "1.10.3"
    assert latest_version_in_line("pkg-v", "0.1") is None


def preview_and_stable_tags(_prefix: str) -> list[str]:
    return ["1.0.6-preview", "1.0.5", "0.1.0-dev.1234", "0.1.0", "v1.0.5"]


def prerelease_only_tags(_prefix: str) -> list[str]:
    return ["1.0.6-preview", "0.1.0-dev.1234"]


def multi_line_tags(_prefix: str) -> list[str]:
    return ["2.4.1", "2.4.0", "1.10.3", "1.9.2", "1.0.10", "1.0.9", "1.0.10-dev.5", "v1.0.9"]


class FakeTagSource:
    def __init__(self, versions: dict[str, list[str]], changed: dict[str, bool]) -> None:
        self.versions = versions
        self.changed = changed

    def latest_version(self, prefix: str) -> str | None:
        versions = self.versions.get(prefix, [])
        return max(versions, key=parse_version) if versions else None

    def latest_version_in_line(self, prefix: str, major_minor: str) -> str | None:
        line = parse_major_minor(major_minor)
        in_line = [version for version in self.versions.get(prefix, []) if parse_version(version)[:2] == line]
        return max(in_line, key=parse_version) if in_line else None

    def has_changes_since(self, tag: str | None, path: Path) -> bool:
        return self.changed.get(path.as_posix(), False)


def patch_plan_tags(monkeypatch: pytest.MonkeyPatch, tags: FakeTagSource) -> None:
    monkeypatch.setattr(plan_module, "latest_version", tags.latest_version)
    monkeypatch.setattr(plan_module, "latest_version_in_line", tags.latest_version_in_line)
    monkeypatch.setattr(plan_module, "has_changes_since", tags.has_changes_since)


ARFOUNDATION_EDGE = DependencyEdge(
    dependency_package="placeframe-core", registry="npm", identity="org.outernet.placeframe"
)
EDGES = {
    "placeframe-api-client": [],
    "placeframe-core": [],
    "placeframe-arfoundation": [ARFOUNDATION_EDGE],
    "placeframe-common": [],
}


def test_next_version_first_in_line_and_patch_bump():
    assert next_version("1.0", None, None, "pkg") == "1.0.0"
    assert next_version("0.1", "0.1.7", "0.1.7", "pkg") == "0.1.8"
    assert next_version("1.9", "1.9.10", "1.9.10", "pkg") == "1.9.11"


def test_next_version_new_line_above_old_tag():
    assert next_version("1.4", None, "1.0.9", "pkg") == "1.4.0"
    assert next_version("2.0", None, "1.9.3", "pkg") == "2.0.0"


def test_next_version_app_derivation():
    assert next_version("1.0", None, None, "capture-tool") == "1.0.0"
    assert next_version("1.0", "1.0.0", "1.0.0", "capture-tool") == "1.0.1"


def test_next_version_guard_rejects_line_below_tagged():
    with pytest.raises(ValueError, match=r"below tags version 1\.5\.2"):
        next_version("1.0", None, "1.5.2", "pkg")
    with pytest.raises(ValueError, match=r"below tags version 1\.0\.0"):
        next_version("0.9", None, "1.0.0", "pkg")


def test_resolve_dependency_versions_co_publishing_rides_the_next_version():
    plans = {
        "placeframe-core": PackagePlan(name="placeframe-core", publish=True, version="1.0.6", last_version="1.0.5"),
    }

    resolved = resolve_dependency_versions(EDGES["placeframe-arfoundation"], plans, {"placeframe-core"})

    assert resolved == {"org.outernet.placeframe": ResolvedDependency(version="1.0.6", co_publishing=True)}


def test_resolve_dependency_versions_unchanged_sibling_rides_the_current_tag():
    plans = {
        "placeframe-core": PackagePlan(name="placeframe-core", publish=False, version="1.0.5", last_version="1.0.5"),
    }

    resolved = resolve_dependency_versions(EDGES["placeframe-arfoundation"], plans, {"placeframe-arfoundation"})

    assert resolved == {"org.outernet.placeframe": ResolvedDependency(version="1.0.5", co_publishing=False)}


def test_resolve_dependency_versions_never_published_sibling_is_loud():
    plans = {
        "placeframe-core": PackagePlan(name="placeframe-core", publish=False, version="0.0.0", last_version=None),
    }

    with pytest.raises(ValueError, match="'placeframe-core' has never published"):
        resolve_dependency_versions(EDGES["placeframe-arfoundation"], plans, {"placeframe-arfoundation"})


def test_resolve_dependency_versions_first_release_pair_co_publishes():
    plans = {
        "placeframe-core": PackagePlan(name="placeframe-core", publish=True, version="1.0.0", last_version=None),
    }

    resolved = resolve_dependency_versions(
        EDGES["placeframe-arfoundation"], plans, {"placeframe-core", "placeframe-arfoundation"}
    )

    assert resolved == {"org.outernet.placeframe": ResolvedDependency(version="1.0.0", co_publishing=True)}


def test_release_plan_refuses_cyclic_dependencies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name, dependency in (("first", "org.example.second"), ("second", "org.example.first")):
        package_dir = tmp_path / name
        package_dir.mkdir()
        (package_dir / "package.json").write_text(
            json.dumps({"name": name, "version": "0.0.0-local", "dependencies": {dependency: SENTINEL_VERSION}}),
            encoding="utf-8",
        )
    packages = {
        "first": PackageConfig(path=Path("first"), major_minor="1.0", registries={"npm": "org.example.first"}),
        "second": PackageConfig(path=Path("second"), major_minor="1.0", registries={"npm": "org.example.second"}),
    }

    with pytest.raises(ValueError, match="cyclic dependency edge"):
        compute_release_plan(PublishConfig(packages=packages))


RELEASE_CONFIG = PublishConfig(
    packages={"pkg": PackageConfig(path=Path("pkg"), major_minor="0.1")},
    apps={"app": AppConfig(path=Path("app"), major_minor="0.2")},
)


def test_release_plan_bumps_apps_when_any_package_publishes(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_plan_tags(monkeypatch, FakeTagSource(versions={"app-v": ["0.2.3"]}, changed={"pkg": True, "app": False}))

    release_plan = compute_release_plan(RELEASE_CONFIG)

    assert release_plan.publishing == {"pkg"}
    assert release_plan.plans["pkg"].version == "0.1.0"
    assert release_plan.app_versions == {"app": "0.2.4"}


def test_release_plan_leaves_everything_unchanged_when_nothing_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_plan_tags(monkeypatch, FakeTagSource(versions={"app-v": ["0.2.3"]}, changed={"pkg": False, "app": False}))

    release_plan = compute_release_plan(RELEASE_CONFIG)

    assert release_plan.publishing == set()
    assert release_plan.app_versions == {}


def test_release_plan_unions_registries_of_publishing_packages_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    changed_path = tmp_path / "changed"
    changed_path.mkdir()
    (changed_path / "package.json").write_text("{}", encoding="utf-8")
    unchanged_path = tmp_path / "unchanged"
    unchanged_path.mkdir()
    (unchanged_path / "un.csproj").write_text("<Project />", encoding="utf-8")
    config = PublishConfig(
        packages={
            "changed": PackageConfig(path=changed_path, major_minor="1.0", registries={"npm": "changed-id"}),
            "unchanged": PackageConfig(path=unchanged_path, major_minor="1.0", registries={"nuget": "unchanged-id"}),
        },
        apps={"app": AppConfig(path=Path("app"), major_minor="0.2")},
    )
    patch_plan_tags(monkeypatch, FakeTagSource(versions={"app-v": ["0.2.3"]}, changed={changed_path.as_posix(): True}))

    release_plan = compute_release_plan(config)

    assert release_plan.publishing == {"changed"}
    assert release_plan.publishing_registries == {"npm"}


def test_release_plan_bumps_app_on_its_own_path_change(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_plan_tags(monkeypatch, FakeTagSource(versions={"app-v": ["0.2.3"]}, changed={"pkg": False, "app": True}))

    release_plan = compute_release_plan(RELEASE_CONFIG)

    assert release_plan.publishing == set()
    assert release_plan.app_versions == {"app": "0.2.4"}


def test_package_rows_use_override_then_tag_then_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    packages = {
        "published": PackageConfig(path=Path("pkg/a"), major_minor="1.0", registries={"npm": "a-id"}),
        "tagged": PackageConfig(path=Path("pkg/b"), major_minor="1.0", registries={"npm": "b-id"}),
        "never": PackageConfig(path=Path("pkg/c"), major_minor="1.0", registries={"npm": "c-id"}),
    }
    patch_plan_tags(monkeypatch, FakeTagSource(versions={"tagged-v": ["1.2.3"]}, changed={}))

    overridden = package_rows(packages, {"published": "1.1.0-dev.abcdef123456"})
    assert [(row.name, row.version) for row in overridden] == [
        ("published", "1.1.0-dev.abcdef123456"),
        ("tagged", "1.2.3"),
        ("never", "0.0.0"),
    ]
    assert overridden[0].registries[0].url is not None
    assert overridden[1].registries[0].url is not None
    assert overridden[2].registries[0].url is None
