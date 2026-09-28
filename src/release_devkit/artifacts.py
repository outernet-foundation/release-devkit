from pathlib import Path

ARTIFACT_DIR = Path("/tmp/release-artifacts")

# Non-release CI artifacts: env lockfiles from lock-python, version reports, build reports
_SKIP_PREFIXES = ("env-lock-", "versions")
_SKIP_SUFFIXES = ("-build-report",)


def is_release_artifact(name: str) -> bool:
    if any(name.startswith(prefix) for prefix in _SKIP_PREFIXES):
        return False
    return not any(name.endswith(suffix) for suffix in _SKIP_SUFFIXES)
