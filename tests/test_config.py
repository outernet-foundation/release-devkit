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
                "registry": "nuget",
                "identity": "PlaceframeApiClient",
            },
            "placeframe-core": {
                "path": "packages/unity/Placeframe/Assets/Package/Core",
                "major_minor": "1.0",
                "registry": "npm",
                "identity": "org.outernet.placeframe",
            },
            "placeframe-arfoundation": {
                "path": "packages/unity/Placeframe/Assets/Package/ARFoundation",
                "major_minor": "1.0",
                "registry": "npm",
                "identity": "org.outernet.placeframe.arfoundation",
            },
        },
        "apps": {
            "capture-tool": {
                "path": "apps/CaptureTool",
                "major_minor": "1.0",
                "builds": [
                    {"project": "CaptureTool", "platform": "AndroidMobile"},
                ],
            },
        },
        "builds_registry": "ghcr.io/outernet-foundation/placeframe-capture-tool/builds",
    }


def test_load_config_parses_packages(tmp_path: Path):
    config = load_config(write_config(tmp_path, base_payload()))

    assert list(config.packages) == [
        "placeframe-api-client",
        "placeframe-core",
        "placeframe-arfoundation",
    ]
    assert config.packages["placeframe-arfoundation"].registry == "npm"
    assert config.packages["placeframe-arfoundation"].identity == "org.outernet.placeframe.arfoundation"
    assert list(config.apps) == ["capture-tool"]


def test_load_config_defaults_empty_collections(tmp_path: Path):
    config_path = tmp_path / "release-devkit.yaml"
    config_path.write_text("", encoding="utf-8")

    config = load_config(config_path)

    assert config.packages == {}
    assert config.apps == {}
    assert config.builds_registry is None


def test_load_config_rejects_unknown_top_level_keys(tmp_path: Path):
    payload: dict[str, object] = {
        "mirror_prefix": "ghcr.io/my-org/mirror",
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_unknown_registries(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["packages"], dict)
    payload["packages"]["placeframe-api-client"]["registry"] = "cargo"

    with pytest.raises(ValidationError, match="unknown registry 'cargo'"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_missing_identity(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["packages"], dict)
    del payload["packages"]["placeframe-api-client"]["identity"]

    with pytest.raises(ValidationError, match="identity"):
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
    payload["apps"]["capture-tool"]["builds"] = [
        {"project": "CaptureTool", "platform": "AndroidMobile"},
        {"project": "capture-tool", "platform": "images-lock", "name": "images-lock-zed.lock"},
    ]

    config = load_config(write_config(tmp_path, payload))

    builds = config.apps["capture-tool"].builds
    assert config.builds_registry == "ghcr.io/outernet-foundation/placeframe-capture-tool/builds"
    assert [(artifact.project, artifact.platform) for artifact in builds] == [
        ("CaptureTool", "AndroidMobile"),
        ("capture-tool", "images-lock"),
    ]
    assert builds[0].name is None
    assert builds[1].name == "images-lock-zed.lock"


def test_load_config_rejects_app_without_builds(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["apps"], dict)
    del payload["apps"]["capture-tool"]["builds"]

    with pytest.raises(ValidationError, match="builds"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_file_selection_key(tmp_path: Path):
    payload = base_payload()
    assert isinstance(payload["apps"], dict)
    payload["apps"]["capture-tool"]["builds"] = [
        {"project": "CaptureTool", "platform": "AndroidMobile", "file": "Capture_Tool.apk"}
    ]

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_config(write_config(tmp_path, payload))


def test_load_config_rejects_apps_without_builds_registry(tmp_path: Path):
    payload = base_payload()
    del payload["builds_registry"]

    with pytest.raises(ValidationError, match="builds_registry is required"):
        load_config(write_config(tmp_path, payload))
