from pathlib import Path

import pytest

from release_devkit.config import AppConfig, PackageConfig, PublishConfig
from release_devkit.tags import GitTags, parse_major_minor, parse_version
from release_devkit.manifests import DependencyEdge
from release_devkit.plan import (
    ResolvedDependency,
    compute_plan,
    compute_release_plan,
    next_version,
    render_plan_summary,
    resolve_dependency_versions,
    topological_order,
)


def test_latest_version_skips_prerelease_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "release_devkit.tags.list_tag_versions",
        preview_and_stable_tags,
    )

    assert GitTags().latest_version("pkg-v") == "1.0.5"


def test_latest_version_returns_none_when_no_stable_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "release_devkit.tags.list_tag_versions",
        prerelease_only_tags,
    )

    assert GitTags().latest_version("pkg-v") is None


def test_latest_version_in_line_filters_to_declared_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "release_devkit.tags.list_tag_versions",
        multi_line_tags,
    )

    tags = GitTags()
    assert tags.latest_version_in_line("pkg-v", "1.0") == "1.0.10"
    assert tags.latest_version_in_line("pkg-v", "1.9") == "1.9.2"
    assert tags.latest_version_in_line("pkg-v", "2.4") == "2.4.1"
    assert tags.latest_version_in_line("pkg-v", "1.10") == "1.10.3"
    assert tags.latest_version_in_line("pkg-v", "0.1") is None


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


API_CLIENT = PackageConfig(
    path=Path("packages/generated/csharp/api-client"),
    major_minor="0.1",
    registries={"nuget": "X", "npm": "N"},
)
CORE = PackageConfig(
    path=Path("packages/unity/Core"),
    major_minor="1.0",
    registries={"npm": "Y"},
)
ARFOUNDATION = PackageConfig(
    path=Path("packages/unity/ARFoundation"),
    major_minor="1.0",
    registries={"npm": "Z"},
)
COMMON = PackageConfig(path=Path("packages/python/common"), major_minor="0.1", registries={"pypi": "P"})
PACKAGES = {
    "placeframe-api-client": API_CLIENT,
    "placeframe-core": CORE,
    "placeframe-arfoundation": ARFOUNDATION,
    "placeframe-common": COMMON,
}
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


def test_plan_first_publish_uses_declared_line():
    tags = FakeTagSource(
        versions={},
        changed={"packages/generated/csharp/api-client": True, "packages/unity/Core": True},
    )

    plans = compute_plan(
        {"placeframe-api-client": API_CLIENT, "placeframe-core": CORE},
        tags,
        {"placeframe-api-client": [], "placeframe-core": []},
    )

    assert plans["placeframe-api-client"].publish is True
    assert plans["placeframe-api-client"].version == "0.1.0"
    assert plans["placeframe-core"].publish is True
    assert plans["placeframe-core"].version == "1.0.0"


def test_plan_unchanged_package_carries_last_version():
    tags = FakeTagSource(
        versions={"placeframe-api-client-v": ["0.1.7"]},
        changed={"packages/generated/csharp/api-client": False},
    )

    plans = compute_plan({"placeframe-api-client": API_CLIENT}, tags, {"placeframe-api-client": []})

    assert plans["placeframe-api-client"].publish is False
    assert plans["placeframe-api-client"].version == "0.1.7"


def test_plan_changed_package_patch_bumps_within_line():
    tags = FakeTagSource(
        versions={"placeframe-api-client-v": ["0.1.7"]},
        changed={"packages/generated/csharp/api-client": True},
    )

    plans = compute_plan({"placeframe-api-client": API_CLIENT}, tags, {"placeframe-api-client": []})

    assert plans["placeframe-api-client"].publish is True
    assert plans["placeframe-api-client"].version == "0.1.8"


def test_plan_line_bump_publishes_first_version_of_new_line():
    tags = FakeTagSource(
        versions={"placeframe-api-client-v": ["1.0.9"]},
        changed={"packages/generated/csharp/api-client": True},
    )

    plans = compute_plan(
        {"placeframe-api-client": API_CLIENT.model_copy(update={"major_minor": "1.4"})},
        tags,
        {"placeframe-api-client": []},
    )

    assert plans["placeframe-api-client"].publish is True
    assert plans["placeframe-api-client"].version == "1.4.0"


def test_plan_guard_errors_when_line_is_below_tagged():
    tags = FakeTagSource(
        versions={"placeframe-api-client-v": ["1.5.2"]},
        changed={"packages/generated/csharp/api-client": True},
    )

    with pytest.raises(ValueError, match=r"placeframe-api-client: declared major\.minor 1\.4 is below tags"):
        compute_plan(
            {"placeframe-api-client": API_CLIENT.model_copy(update={"major_minor": "1.4"})},
            tags,
            {"placeframe-api-client": []},
        )


def test_plan_no_cascade_unchanged_dependent_does_not_publish():
    tags = FakeTagSource(
        versions={"placeframe-core-v": ["1.0.5"]},
        changed={
            "packages/unity/Core": True,
            "packages/unity/ARFoundation": False,
        },
    )

    plans = compute_plan(PACKAGES, tags, EDGES)

    assert plans["placeframe-core"].publish is True
    assert plans["placeframe-core"].version == "1.0.6"
    assert plans["placeframe-arfoundation"].publish is False
    assert plans["placeframe-arfoundation"].version == "0.0.0"


def test_topological_order_places_dependencies_first_regardless_of_config_order():
    ordered = topological_order({"placeframe-arfoundation": ARFOUNDATION, "placeframe-core": CORE}, EDGES)

    assert ordered == ["placeframe-core", "placeframe-arfoundation"]


def test_topological_order_preserves_config_order_without_edges():
    ordered = topological_order(PACKAGES, EDGES)

    assert ordered == [
        "placeframe-api-client",
        "placeframe-core",
        "placeframe-arfoundation",
        "placeframe-common",
    ]


def test_topological_order_rejects_cycles():
    cycle_edges = {
        "placeframe-core": [DependencyEdge(dependency_package="placeframe-arfoundation", registry="npm", identity="a")],
        "placeframe-arfoundation": [ARFOUNDATION_EDGE],
    }

    with pytest.raises(ValueError, match="cyclic dependency edge"):
        topological_order({"placeframe-core": CORE, "placeframe-arfoundation": ARFOUNDATION}, cycle_edges)


def test_topological_order_rejects_self_edges():
    self_edges = {
        "placeframe-core": [DependencyEdge(dependency_package="placeframe-core", registry="npm", identity="Y")]
    }

    with pytest.raises(ValueError, match="cyclic dependency edge"):
        topological_order({"placeframe-core": CORE}, self_edges)


def test_resolve_dependency_versions_co_publishing_rides_the_next_version():
    tags = FakeTagSource(
        versions={"placeframe-core-v": ["1.0.5"]},
        changed={"packages/unity/Core": True, "packages/unity/ARFoundation": True},
    )
    plans = compute_plan(PACKAGES, tags, EDGES)

    resolved = resolve_dependency_versions(EDGES["placeframe-arfoundation"], plans, {"placeframe-core"})

    assert resolved == {"org.outernet.placeframe": ResolvedDependency(version="1.0.6", co_publishing=True)}


def test_resolve_dependency_versions_unchanged_sibling_rides_the_current_tag():
    tags = FakeTagSource(
        versions={"placeframe-core-v": ["1.0.5"]},
        changed={"packages/unity/Core": False, "packages/unity/ARFoundation": True},
    )
    plans = compute_plan(PACKAGES, tags, EDGES)

    resolved = resolve_dependency_versions(EDGES["placeframe-arfoundation"], plans, {"placeframe-arfoundation"})

    assert resolved == {"org.outernet.placeframe": ResolvedDependency(version="1.0.5", co_publishing=False)}


def test_resolve_dependency_versions_never_published_sibling_is_loud():
    tags = FakeTagSource(
        versions={},
        changed={"packages/unity/ARFoundation": True},
    )
    plans = compute_plan(PACKAGES, tags, EDGES)

    with pytest.raises(ValueError, match="'placeframe-core' has never published"):
        resolve_dependency_versions(EDGES["placeframe-arfoundation"], plans, {"placeframe-arfoundation"})


def test_resolve_dependency_versions_first_release_pair_co_publishes():
    tags = FakeTagSource(
        versions={},
        changed={"packages/unity/Core": True, "packages/unity/ARFoundation": True},
    )
    plans = compute_plan(PACKAGES, tags, EDGES)

    resolved = resolve_dependency_versions(
        EDGES["placeframe-arfoundation"], plans, {"placeframe-core", "placeframe-arfoundation"}
    )

    assert resolved == {"org.outernet.placeframe": ResolvedDependency(version="1.0.0", co_publishing=True)}


RELEASE_CONFIG = PublishConfig(
    packages={"pkg": PackageConfig(path=Path("pkg"), major_minor="0.1")},
    apps={"app": AppConfig(path=Path("app"), major_minor="0.2")},
    ci_workflow="release.yml",
)


def test_release_plan_bumps_apps_when_any_package_publishes():
    tags = FakeTagSource(versions={"app-v": ["0.2.3"]}, changed={"pkg": True, "app": False})

    release_plan = compute_release_plan(RELEASE_CONFIG, tags)

    assert release_plan.publishing == {"pkg"}
    assert release_plan.plans["pkg"].version == "0.1.0"
    assert release_plan.app_versions == {"app": "0.2.4"}
    assert release_plan.anything_releases() is True


def test_release_plan_leaves_everything_unchanged_when_nothing_changed():
    tags = FakeTagSource(versions={"app-v": ["0.2.3"]}, changed={"pkg": False, "app": False})

    release_plan = compute_release_plan(RELEASE_CONFIG, tags)

    assert release_plan.publishing == set()
    assert release_plan.app_versions == {}
    assert release_plan.anything_releases() is False


def test_release_plan_bumps_app_on_its_own_path_change():
    tags = FakeTagSource(versions={"app-v": ["0.2.3"]}, changed={"pkg": False, "app": True})

    release_plan = compute_release_plan(RELEASE_CONFIG, tags)

    assert release_plan.publishing == set()
    assert release_plan.app_versions == {"app": "0.2.4"}


def test_render_plan_summary_lists_apps_with_old_and_new_versions():
    tags = FakeTagSource(versions={"app-v": ["0.2.3"]}, changed={"pkg": True, "app": False})

    release_plan = compute_release_plan(RELEASE_CONFIG, tags)

    summary = render_plan_summary(release_plan)
    assert "### Publish Plan" in summary
    assert "| pkg | True | 0.1.0 |" in summary
    assert "- app: 0.2.3 -> 0.2.4" in summary
