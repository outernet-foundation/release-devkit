from __future__ import annotations

import json
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, TypeGuard

import typer
import yaml
from bashrun.bash import CalledProcessError, bash, bash_output

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

ACTIONLINT_VERSION = "1.7.12"
CHECKOUT_USES = "actions/checkout@v5"
DEVKIT_ACTION_PREFIX = "./.release-devkit/.github/actions/"
SNAPSHOT_REF = "${{ github.head_ref || github.ref_name }}"
DEVKIT_REF = "${{ env.RELEASE_DEVKIT_SHA }}"
DEVKIT_REPOSITORY = "outernet-foundation/release-devkit"
DEVKIT_PIN = re.compile(r"^[0-9a-f]{40}$")

CONSUMER_LEDGER = "consumer-ledger"
CONSUMER_LEDGER_PUSH = "consumer-ledger-push"
SNAPSHOT = "snapshot"
HOUSEMATE = "housemate"

SIGNATURES: dict[str, dict[str, object]] = {
    CONSUMER_LEDGER: {"fetch-depth": 0, "fetch-tags": True, "persist-credentials": False},
    CONSUMER_LEDGER_PUSH: {"fetch-depth": 0, "fetch-tags": True},
    SNAPSHOT: {"ref": SNAPSHOT_REF, "persist-credentials": False},
    HOUSEMATE: {
        "repository": DEVKIT_REPOSITORY,
        "ref": DEVKIT_REF,
        "path": ".release-devkit",
        "persist-credentials": False,
    },
}

PLATFORMS = {
    ("Linux", "x86_64"): "linux_amd64",
    ("Linux", "aarch64"): "linux_arm64",
    ("Darwin", "x86_64"): "darwin_amd64",
    ("Darwin", "arm64"): "darwin_arm64",
}


@dataclass
class CheckoutStep:
    step_index: int
    signature: str


@dataclass
class VerbStep:
    step_index: int
    name: str
    dry_run: bool


@app.command()
def main(
    workflows: Annotated[
        list[Path] | None,
        typer.Option("--workflow", help="Workflow file to signature-validate (repeatable; default ci-cd.yml)"),
    ] = None,
) -> None:
    workflow_paths = workflows or [Path(".github/workflows/ci-cd.yml")]
    problems: list[str] = []
    for workflow_path in workflow_paths:
        problems.extend(validate_workflow_file(workflow_path))
    for problem in problems:
        print(problem)
    run_actionlint()
    if problems:
        raise SystemExit(1)


def is_mapping(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def validate_workflow_file(path: Path) -> list[str]:
    if not path.is_file():
        return [f"{path}: workflow file not found"]
    document: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not is_mapping(document):
        return [f"{path}: workflow is not a YAML mapping"]
    problems = validate_devkit_pin(document, path)
    jobs_value = document.get("jobs")
    if not is_mapping(jobs_value):
        return [*problems, f"{path}: no jobs mapping"]
    for job_name, job_value in jobs_value.items():
        problems.extend(validate_job(str(job_name), job_value, path))
    return problems


def validate_devkit_pin(document: dict[object, object], path: Path) -> list[str]:
    env_value = document.get("env")
    pin = env_value.get("RELEASE_DEVKIT_SHA") if is_mapping(env_value) else None
    if not isinstance(pin, str) or not DEVKIT_PIN.fullmatch(pin):
        return [f"{path}: env.RELEASE_DEVKIT_SHA must be a full commit SHA at workflow level"]
    return []


def validate_job(job_name: str, job_value: object, path: Path) -> list[str]:
    if not is_mapping(job_value):
        return [f"{path}: job '{job_name}' is not a mapping"]
    steps_value = job_value.get("steps")
    steps = steps_value if is_object_list(steps_value) else []
    checkout_steps, problems = collect_checkout_steps(job_name, steps, path)
    verb_steps = collect_verb_steps(steps)
    if not verb_steps:
        return problems
    is_real_publish = any(verb.name == "publish-stable" and not verb.dry_run for verb in verb_steps)
    required_consumer = CONSUMER_LEDGER_PUSH if is_real_publish else CONSUMER_LEDGER
    if not is_real_publish and any(step.signature == CONSUMER_LEDGER_PUSH for step in checkout_steps):
        problems.append(
            f"{path}: job '{job_name}': consumer-ledger-push checkout is reserved for real publish-stable jobs"
        )
    first_verb_index = min(verb.step_index for verb in verb_steps)
    housemates = [step for step in checkout_steps if step.signature == HOUSEMATE and step.step_index < first_verb_index]
    if not housemates:
        problems.append(f"{path}: job '{job_name}': no housemate checkout precedes the release-devkit verb")
        return problems
    earliest_housemate_index = min(step.step_index for step in housemates)
    has_consumer = any(
        step.signature == required_consumer and step.step_index < earliest_housemate_index for step in checkout_steps
    )
    if not has_consumer:
        problems.append(f"{path}: job '{job_name}': no {required_consumer} checkout precedes the housemate checkout")
    return problems


def collect_verb_steps(steps: list[object]) -> list[VerbStep]:
    verb_steps: list[VerbStep] = []
    for index, step_value in enumerate(steps):
        if not is_mapping(step_value):
            continue
        uses_value = step_value.get("uses")
        if not (isinstance(uses_value, str) and uses_value.startswith(DEVKIT_ACTION_PREFIX)):
            continue
        with_value = step_value.get("with")
        dry_run = is_mapping(with_value) and with_value.get("dry-run") is True
        verb_steps.append(
            VerbStep(step_index=index, name=uses_value.removeprefix(DEVKIT_ACTION_PREFIX), dry_run=dry_run)
        )
    return verb_steps


def collect_checkout_steps(job_name: str, steps: list[object], path: Path) -> tuple[list[CheckoutStep], list[str]]:
    checkout_steps: list[CheckoutStep] = []
    problems: list[str] = []
    for index, step_value in enumerate(steps):
        if not is_mapping(step_value):
            continue
        uses_value = step_value.get("uses")
        if not isinstance(uses_value, str):
            continue
        if uses_value.startswith("actions/checkout") and uses_value != CHECKOUT_USES:
            problems.append(
                f"{path}: job '{job_name}' step {index}: checkout must be {CHECKOUT_USES}, got {uses_value}"
            )
            continue
        if uses_value != CHECKOUT_USES:
            continue
        with_value = step_value.get("with")
        with_block: dict[str, object] = with_value if is_string_mapping(with_value) else {}
        signature = next((name for name, expected in SIGNATURES.items() if with_block == expected), None)
        if signature is None:
            rendered = json.dumps(with_block, sort_keys=True)
            problems.append(f"{path}: job '{job_name}' step {index}: checkout matches no signature; with={rendered}")
        else:
            checkout_steps.append(CheckoutStep(step_index=index, signature=signature))
    return checkout_steps, problems


def is_string_mapping(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def run_actionlint() -> None:
    workflows_directory = Path(".github/workflows")
    workflow_files = sorted(workflows_directory.glob("*.yml")) if workflows_directory.is_dir() else []
    if not workflow_files:
        raise SystemExit("no .github/workflows/*.yml files found")
    command = " ".join(str(part) for part in [ensure_actionlint(), *workflow_files])
    try:
        bash(command)
    except CalledProcessError as error:
        raise SystemExit(error.returncode) from error


def ensure_actionlint() -> Path:
    cache_directory = actionlint_cache_dir()
    binary = cache_directory / "actionlint"
    if binary.is_file():
        return binary
    cache_directory.mkdir(parents=True, exist_ok=True)
    platform_key = (platform.system(), platform.machine())
    if platform_key not in PLATFORMS:
        raise SystemExit(f"no actionlint build for {platform.system()}/{platform.machine()}")
    build = PLATFORMS[platform_key]
    release_base = f"https://github.com/rhysd/actionlint/releases/download/v{ACTIONLINT_VERSION}"
    tarball_name = f"actionlint_{ACTIONLINT_VERSION}_{build}.tar.gz"
    tarball = cache_directory / tarball_name
    bash(f"curl -fsSL {release_base}/{tarball_name} -o {tarball}")
    checksums = bash_output(f"curl -fsSL {release_base}/actionlint_{ACTIONLINT_VERSION}_checksums.txt")
    expected = expected_checksum(checksums, tarball_name)
    actual = bash_output(f"sha256sum {tarball}").split(maxsplit=1)[0]
    if actual != expected:
        raise SystemExit(
            f"actionlint {ACTIONLINT_VERSION} checksum mismatch for {tarball_name}: expected {expected}, got {actual}"
        )
    bash(f"tar -xzf {tarball} -C {cache_directory}")
    if not binary.is_file():
        raise SystemExit(f"actionlint binary missing after extracting {tarball_name}")
    return binary


def actionlint_cache_dir() -> Path:
    return Path.home() / ".cache" / "release-devkit" / f"actionlint-v{ACTIONLINT_VERSION}"


def expected_checksum(checksums: str, tarball_name: str) -> str:
    for line in checksums.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == tarball_name:
            return fields[0]
    raise SystemExit(f"actionlint checksums file has no entry for {tarball_name}")
