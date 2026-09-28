import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from release_devkit.config import PackageConfig, load_config, select_packages


def write_config(tmp_path: Path, payload: dict[str, object]) -> Path:
    config_path = tmp_path / "release-devkit.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def base_payload() -> dict[str, object]:
    return {
        "packages": [
            {
                "name": "placeframe-api-client",
                "path": "packages/generated/csharp/api-client/src/PlaceframeApiClient",
                "major_minor": "0.1",
                "registries": {"nuget": "PlaceframeApiClient"},
            },
            {
                "name": "placeframe-core",
                "path": "packages/unity/Placeframe/Assets/Package/Core",
                "major_minor": "1.0",
                "registries": {"npm": "org.outernet.placeframe"},
            },
            {
                "name": "placeframe-arfoundation",
                "path": "packages/unity/Placeframe/Assets/Package/ARFoundation",
                "major_minor": "1.0",
                "registries": {"npm": "org.outernet.placeframe.arfoundation"},
            },
        ],
        "apps": [
            {
                "name": "CaptureTool",
                "path": "apps/CaptureTool",
                "major_minor": "1.0",
                "tag_prefix": "capture-tool",
                "display_name": "Capture Tool",
            },
        ],
        "ci_workflow": "placeframe-ci.yml",
    }


def test_load_config_parses_packages(tmp_path: Path):
    config = load_config(write_config(tmp_path, base_payload()))

    assert [p.name for p in config.packages] == [
        "placeframe-api-client",
        "placeframe-core",
        "placeframe-arfoundation",
    ]
    assert config.packages[2].registries == {"npm": "org.outernet.placeframe.arfoundation"}
    assert config.apps[0].tag_prefix == "capture-tool"


def test_load_config_defaults_empty_collections(tmp_path: Path):
    payload: dict[str, object] = {
        "ci_workflow": "my-ci.yml",
    }

    config = load_config(write_config(tmp_path, payload))

    assert config.packages == []
    assert config.apps == []


def test_load_config_rejects_the_old_feeds_key(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["packages"], list)
    payload["packages"][1]["feeds"] = payload["packages"][1]["registries"]
    del payload["packages"][1]["registries"]

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_unknown_top_level_keys(tmp_path: Path):
    payload: dict[str, object] = {
        "ci_workflow": "my-ci.yml",
        "mirror_prefix": "ghcr.io/my-org/mirror",
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_unknown_registries(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["packages"], list)
    payload["packages"][0]["registries"] = {"cargo": "placeframe"}

    with pytest.raises(ValidationError, match="unknown registries: \\['cargo'\\]"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_duplicate_package_names(tmp_path: Path):
    payload = base_payload()
    original = payload["packages"]
    assert isinstance(original, list)
    payload["packages"] = [*original, original[1]]
    with pytest.raises(ValidationError, match="duplicate package name 'placeframe-core'"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_depends_on_entries(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["packages"], list)
    payload["packages"][2]["depends_on"] = ["placeframe-core"]

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_dependency_pins_entries(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["packages"], list)
    payload["packages"][2]["dependency_pins"] = {"org.outernet.placeframe": "placeframe-core"}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_missing_major_minor(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["packages"], list)
    del payload["packages"][0]["major_minor"]

    with pytest.raises(ValidationError, match="major_minor"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_malformed_major_minor(tmp_path: Path):
    for malformed in ["1", "1.0.0", "v1.0", "latest"]:
        payload = base_payload()
        assert isinstance(payload["packages"], list)
        payload["packages"][0]["major_minor"] = malformed

        with pytest.raises(ValidationError, match="major_minor"):
            load_config(write_config(tmp_path, payload))


def package_names(packages: list[PackageConfig]) -> list[str]:
    return [package.name for package in packages]


def loaded_packages(tmp_path: Path) -> list[PackageConfig]:
    return load_config(write_config(tmp_path, base_payload())).packages


def test_select_packages_only_preserves_config_order(tmp_path: Path):
    packages = loaded_packages(tmp_path)

    selected = select_packages(packages, ["placeframe-arfoundation", "placeframe-api-client"], [])

    assert package_names(selected) == ["placeframe-api-client", "placeframe-arfoundation"]


def test_select_packages_exclude(tmp_path: Path):
    packages = loaded_packages(tmp_path)

    selected = select_packages(packages, [], ["placeframe-core"])

    assert package_names(selected) == ["placeframe-api-client", "placeframe-arfoundation"]


def test_select_packages_unfiltered_returns_all(tmp_path: Path):
    packages = loaded_packages(tmp_path)

    assert package_names(select_packages(packages, [], [])) == [
        "placeframe-api-client",
        "placeframe-core",
        "placeframe-arfoundation",
    ]


def test_select_packages_rejects_unknown_name(tmp_path: Path):
    packages = loaded_packages(tmp_path)

    with pytest.raises(SystemExit, match="Unknown package 'nope'"):
        select_packages(packages, ["nope"], [])


def test_select_packages_rejects_only_with_exclude(tmp_path: Path):
    packages = loaded_packages(tmp_path)

    with pytest.raises(SystemExit, match="mutually exclusive"):
        select_packages(packages, ["placeframe-core"], ["placeframe-core"])
