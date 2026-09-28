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
        "packages": {
            "placeframe-api-client": {
                "path": "packages/generated/csharp/api-client/src/PlaceframeApiClient",
                "major_minor": "0.1",
                "registries": {"nuget": "PlaceframeApiClient"},
            },
            "placeframe-core": {
                "path": "packages/unity/Placeframe/Assets/Package/Core",
                "major_minor": "1.0",
                "registries": {"npm": "org.outernet.placeframe"},
            },
            "placeframe-arfoundation": {
                "path": "packages/unity/Placeframe/Assets/Package/ARFoundation",
                "major_minor": "1.0",
                "registries": {"npm": "org.outernet.placeframe.arfoundation"},
            },
        },
        "apps": {
            "capture-tool": {
                "path": "apps/CaptureTool",
                "major_minor": "1.0",
            },
        },
        "ci_workflow": "placeframe-ci.yml",
    }


def test_load_config_parses_packages(tmp_path: Path):
    config = load_config(write_config(tmp_path, base_payload()))

    assert list(config.packages) == [
        "placeframe-api-client",
        "placeframe-core",
        "placeframe-arfoundation",
    ]
    assert config.packages["placeframe-arfoundation"].registries == {"npm": "org.outernet.placeframe.arfoundation"}
    assert list(config.apps) == ["capture-tool"]


def test_load_config_defaults_empty_collections(tmp_path: Path):
    payload: dict[str, object] = {
        "ci_workflow": "my-ci.yml",
    }

    config = load_config(write_config(tmp_path, payload))

    assert config.packages == {}
    assert config.apps == {}


def test_load_config_rejects_the_old_feeds_key(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["packages"], dict)
    payload["packages"]["placeframe-core"]["feeds"] = payload["packages"]["placeframe-core"]["registries"]
    del payload["packages"]["placeframe-core"]["registries"]

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
    assert isinstance(payload["packages"], dict)
    payload["packages"]["placeframe-api-client"]["registries"] = {"cargo": "placeframe"}

    with pytest.raises(ValidationError, match="unknown registries: \\['cargo'\\]"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_depends_on_entries(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["packages"], dict)
    payload["packages"]["placeframe-arfoundation"]["depends_on"] = ["placeframe-core"]

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_dependency_pins_entries(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["packages"], dict)
    payload["packages"]["placeframe-arfoundation"]["dependency_pins"] = {"org.outernet.placeframe": "placeframe-core"}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_missing_major_minor(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["packages"], dict)
    del payload["packages"]["placeframe-api-client"]["major_minor"]

    with pytest.raises(ValidationError, match="major_minor"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_malformed_major_minor(tmp_path: Path):
    for malformed in ["1", "1.0.0", "v1.0", "latest"]:
        payload = base_payload()
        assert isinstance(payload["packages"], dict)
        payload["packages"]["placeframe-api-client"]["major_minor"] = malformed

        with pytest.raises(ValidationError, match="major_minor"):
            load_config(write_config(tmp_path, payload))


def package_names(packages: dict[str, PackageConfig]) -> list[str]:
    return list(packages)


def loaded_packages(tmp_path: Path) -> dict[str, PackageConfig]:
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


REPO_CONFIG = Path(__file__).resolve().parent.parent / "release-devkit.json"


def test_repo_release_devkit_json_loads() -> None:
    config = load_config(REPO_CONFIG)

    assert "release-devkit" in config.packages
    assert config.ci_workflow == "ci.yml"
