from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from release_devkit.config import load_config


def write_config(tmp_path: Path, payload: dict[str, object]) -> Path:
    config_path = tmp_path / "release-devkit.yaml"
    config_path.write_text(
        yaml.safe_dump(payload, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
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
    config_path = tmp_path / "release-devkit.yaml"
    config_path.write_text("", encoding="utf-8")

    config = load_config(config_path)

    assert config.packages == {}
    assert config.apps == {}
    assert config.builds_registry is None


def test_load_config_rejects_the_old_feeds_key(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["packages"], dict)
    payload["packages"]["placeframe-core"]["feeds"] = payload["packages"]["placeframe-core"]["registries"]
    del payload["packages"]["placeframe-core"]["registries"]

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_unknown_top_level_keys(tmp_path: Path):
    payload: dict[str, object] = {
        "mirror_prefix": "ghcr.io/my-org/mirror",
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_the_retired_ci_workflow_key(tmp_path: Path):
    payload: dict[str, object] = {
        "ci_workflow": "my-ci.yml",
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


REPO_CONFIG = Path(__file__).resolve().parent.parent / "release-devkit.yaml"


def test_repo_release_devkit_yaml_loads() -> None:
    config = load_config(REPO_CONFIG)

    assert config.packages == {}
    assert config.apps == {}


def test_load_config_rejects_duplicate_keys(tmp_path: Path):
    config_path = tmp_path / "release-devkit.yaml"
    config_path.write_text("builds_registry: a\nbuilds_registry: b\n", encoding="utf-8")

    with pytest.raises(Exception, match=r"Duplicate key"):
        load_config(config_path)


def test_load_config_parses_app_builds_shelf(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["apps"], dict)
    payload["builds_registry"] = "ghcr.io/outernet-foundation/placeframe-capture-tool/builds"
    payload["apps"]["capture-tool"]["builds"] = [
        {"project": "CaptureTool", "platform": "AndroidMobile", "file": "Capture_Tool.apk"},
        {"project": "capture-tool", "platform": "images-lock", "name": "images-lock-zed.lock"},
    ]

    config = load_config(write_config(tmp_path, payload))

    builds = config.apps["capture-tool"].builds
    assert builds is not None
    assert config.builds_registry == "ghcr.io/outernet-foundation/placeframe-capture-tool/builds"
    assert [(artifact.project, artifact.platform) for artifact in builds] == [
        ("CaptureTool", "AndroidMobile"),
        ("capture-tool", "images-lock"),
    ]
    assert builds[0].name is None
    assert builds[1].name == "images-lock-zed.lock"


def test_load_config_rejects_unknown_builds_key(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["apps"], dict)
    payload["builds_registry"] = "ghcr.io/outernet-foundation/placeframe-capture-tool/builds"
    payload["apps"]["capture-tool"]["builds"] = [
        {"project": "CaptureTool", "platform": "AndroidMobile", "shard": "zed"},
    ]

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_config(write_config(tmp_path, payload))
