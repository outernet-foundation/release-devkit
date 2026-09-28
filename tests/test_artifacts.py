from release_devkit.artifacts import is_release_artifact


def test_is_release_artifact_keeps_release_artifacts():
    assert is_release_artifact("CaptureTool")
    assert is_release_artifact("placeframe-api-client")


def test_is_release_artifact_prunes_env_locks():
    assert not is_release_artifact("env-lock-capture-tool")


def test_is_release_artifact_prunes_version_reports():
    assert not is_release_artifact("versions")


def test_is_release_artifact_prunes_build_reports():
    assert not is_release_artifact("capture-tool-build-report")
