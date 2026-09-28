from pathlib import Path

import pytest

from release_devkit.config import PackageConfig
from release_devkit.ledger import GitLedger, parse_major_minor, parse_version
from release_devkit.manifests import DependencyEdge
from release_devkit.plan import (
    PackagePlan,
    ResolvedDependency,
    TagLedger,
    compute_plan,
    next_version,
    render_dev_summary,
    render_summary,
    resolve_dependency_versions,
    topological_order,
)


def test_latest_version_skips_prerelease_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "release_devkit.ledger.list_tag_versions",
        preview_and_stable_tags,
    )

    assert GitLedger().latest_version("pkg-v") == "1.0.5"


def test_latest_version_returns_none_when_no_stable_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "release_devkit.ledger.list_tag_versions",
        prerelease_only_tags,
    )

    assert GitLedger().latest_version("pkg-v") is None


def test_latest_version_in_line_filters_to_declared_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "release_devkit.ledger.list_tag_versions",
        multi_line_tags,
    )

    ledger = GitLedger()
    assert ledger.latest_version_in_line("pkg-v", "1.0") == "1.0.10"
    assert ledger.latest_version_in_line("pkg-v", "1.9") == "1.9.2"
    assert ledger.latest_version_in_line("pkg-v", "2.4") == "2.4.1"
    assert ledger.latest_version_in_line("pkg-v", "1.10") == "1.10.3"
    assert ledger.latest_version_in_line("pkg-v", "0.1") is None


def preview_and_stable_tags(_prefix: str) -> list[str]:
    return ["1.0.6-preview", "1.0.5", "0.1.0-dev.1234", "0.1.0", "v1.0.5"]


def prerelease_only_tags(_prefix: str) -> list[str]:
    return ["1.0.6-preview", "0.1.0-dev.1234"]


def multi_line_tags(_prefix: str) -> list[str]:
    return ["2.4.1", "2.4.0", "1.10.3", "1.9.2", "1.0.10", "1.0.9", "1.0.10-dev.5", "v1.0.9"]


class FakeLedger:
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


def test_next_version_new_line_above_old_ledger():
    assert next_version("1.4", None, "1.0.9", "pkg") == "1.4.0"
    assert next_version("2.0", None, "1.9.3", "pkg") == "2.0.0"


def test_next_version_app_derivation():
    assert next_version("1.0", None, None, "capture-tool") == "1.0.0"
    assert next_version("1.0", "1.0.0", "1.0.0", "capture-tool") == "1.0.1"


def test_next_version_guard_rejects_line_below_ledger():
    with pytest.raises(ValueError, match=r"below ledger version 1\.5\.2"):
        next_version("1.0", None, "1.5.2", "pkg")
    with pytest.raises(ValueError, match=r"below ledger version 1\.0\.0"):
        next_version("0.9", None, "1.0.0", "pkg")


def test_plan_first_publish_uses_declared_line():
    ledger = FakeLedger(
        versions={},
        changed={"packages/generated/csharp/api-client": True, "packages/unity/Core": True},
    )

    plans = compute_plan(
        {"placeframe-api-client": API_CLIENT, "placeframe-core": CORE},
        ledger,
        {"placeframe-api-client": [], "placeframe-core": []},
    )

    assert plans["placeframe-api-client"].publish is True
    assert plans["placeframe-api-client"].version == "0.1.0"
    assert plans["placeframe-core"].publish is True
    assert plans["placeframe-core"].version == "1.0.0"


def test_plan_unchanged_package_carries_last_version():
    ledger = FakeLedger(
        versions={"placeframe-api-client-v": ["0.1.7"]},
        changed={"packages/generated/csharp/api-client": False},
    )

    plans = compute_plan({"placeframe-api-client": API_CLIENT}, ledger, {"placeframe-api-client": []})

    assert plans["placeframe-api-client"].publish is False
    assert plans["placeframe-api-client"].version == "0.1.7"


def test_plan_changed_package_patch_bumps_within_line():
    ledger = FakeLedger(
        versions={"placeframe-api-client-v": ["0.1.7"]},
        changed={"packages/generated/csharp/api-client": True},
    )

    plans = compute_plan({"placeframe-api-client": API_CLIENT}, ledger, {"placeframe-api-client": []})

    assert plans["placeframe-api-client"].publish is True
    assert plans["placeframe-api-client"].version == "0.1.8"


def test_plan_line_bump_publishes_first_version_of_new_line():
    ledger = FakeLedger(
        versions={"placeframe-api-client-v": ["1.0.9"]},
        changed={"packages/generated/csharp/api-client": True},
    )

    plans = compute_plan(
        {"placeframe-api-client": API_CLIENT.model_copy(update={"major_minor": "1.4"})},
        ledger,
        {"placeframe-api-client": []},
    )

    assert plans["placeframe-api-client"].publish is True
    assert plans["placeframe-api-client"].version == "1.4.0"


def test_plan_guard_errors_when_line_is_below_ledger():
    ledger = FakeLedger(
        versions={"placeframe-api-client-v": ["1.5.2"]},
        changed={"packages/generated/csharp/api-client": True},
    )

    with pytest.raises(ValueError, match=r"placeframe-api-client: declared major\.minor 1\.4 is below ledger"):
        compute_plan(
            {"placeframe-api-client": API_CLIENT.model_copy(update={"major_minor": "1.4"})},
            ledger,
            {"placeframe-api-client": []},
        )


def test_plan_no_cascade_unchanged_dependent_does_not_publish():
    ledger = FakeLedger(
        versions={"placeframe-core-v": ["1.0.5"]},
        changed={
            "packages/unity/Core": True,
            "packages/unity/ARFoundation": False,
        },
    )

    plans = compute_plan(PACKAGES, ledger, EDGES)

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
    ledger = FakeLedger(
        versions={"placeframe-core-v": ["1.0.5"]},
        changed={"packages/unity/Core": True, "packages/unity/ARFoundation": True},
    )
    plans = compute_plan(PACKAGES, ledger, EDGES)

    resolved = resolve_dependency_versions(EDGES["placeframe-arfoundation"], plans, {"placeframe-core"})

    assert resolved == {"org.outernet.placeframe": ResolvedDependency(version="1.0.6", co_publishing=True)}


def test_resolve_dependency_versions_unchanged_sibling_rides_the_current_tag():
    ledger = FakeLedger(
        versions={"placeframe-core-v": ["1.0.5"]},
        changed={"packages/unity/Core": False, "packages/unity/ARFoundation": True},
    )
    plans = compute_plan(PACKAGES, ledger, EDGES)

    resolved = resolve_dependency_versions(EDGES["placeframe-arfoundation"], plans, {"placeframe-arfoundation"})

    assert resolved == {"org.outernet.placeframe": ResolvedDependency(version="1.0.5", co_publishing=False)}


def test_resolve_dependency_versions_never_published_sibling_is_loud():
    ledger = FakeLedger(
        versions={},
        changed={"packages/unity/ARFoundation": True},
    )
    plans = compute_plan(PACKAGES, ledger, EDGES)

    with pytest.raises(ValueError, match="'placeframe-core' has never published"):
        resolve_dependency_versions(EDGES["placeframe-arfoundation"], plans, {"placeframe-arfoundation"})


def test_resolve_dependency_versions_first_release_pair_co_publishes():
    ledger = FakeLedger(
        versions={},
        changed={"packages/unity/Core": True, "packages/unity/ARFoundation": True},
    )
    plans = compute_plan(PACKAGES, ledger, EDGES)

    resolved = resolve_dependency_versions(
        EDGES["placeframe-arfoundation"], plans, {"placeframe-core", "placeframe-arfoundation"}
    )

    assert resolved == {"org.outernet.placeframe": ResolvedDependency(version="1.0.0", co_publishing=True)}


def test_render_summary_lists_every_package():
    ledger = FakeLedger(
        versions={"placeframe-core-v": ["1.0.5"]},
        changed={
            "packages/generated/csharp/api-client": True,
            "packages/unity/Core": False,
            "packages/unity/ARFoundation": False,
        },
    )
    plans = compute_plan(PACKAGES, ledger, EDGES)

    summary = render_summary(plans)

    assert "| placeframe-api-client | True | 0.1.0 |" in summary
    assert "| placeframe-core | False | 1.0.5 |" in summary
    assert "| placeframe-arfoundation | False | 0.0.0 |" in summary


def test_render_dev_summary_lists_per_registry_versions():
    ledger = FakeLedger(
        versions={},
        changed={
            "packages/generated/csharp/api-client": True,
            "packages/unity/Core": False,
            "packages/unity/ARFoundation": False,
            "packages/python/common": True,
        },
    )
    plans = compute_plan(PACKAGES, ledger, EDGES)

    summary = render_dev_summary(PACKAGES, plans, "4242")

    assert "| placeframe-api-client | True | nuget: X @ 0.1.0-dev.4242, npm: N @ 0.1.0-dev.4242 |" in summary
    assert "| placeframe-common | True | pypi: P @ 0.1.0.dev4242 |" in summary
    assert "| placeframe-core | False | - |" in summary


def test_fake_ledger_satisfies_protocol():
    ledger: TagLedger = FakeLedger(versions={}, changed={})
    assert ledger.latest_version("x-v") is None


def test_package_plan_dataclass_shape():
    plan = PackagePlan(name="pkg", publish=True, version="1.0.0", last_version="0.9.0")
    assert plan.name == "pkg"
