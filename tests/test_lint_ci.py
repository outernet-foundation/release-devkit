from pathlib import Path

from release_devkit.lint_ci import validate_devkit_wrapper, validate_workflow_file


def write_workflow(tmp_path: Path, text: str) -> Path:
    workflow_path = tmp_path / "integrate.yml"
    workflow_path.write_text(text, encoding="utf-8")
    return workflow_path


CONSUMER_LEDGER_BLOCK = """
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
          fetch-tags: true
          persist-credentials: false
"""

CONSUMER_LEDGER_PUSH_BLOCK = """
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
          fetch-tags: true
"""

WRAPPER_STEP = """
      - uses: ./.github/actions/checkout-release-devkit
"""


def workflow(jobs: str) -> str:
    return f"jobs:\n{jobs}"


def test_valid_verb_job_has_no_problems(tmp_path: Path) -> None:
    jobs = f"  preflight:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}      - uses: ./.release-devkit/.github/actions/get-app-version\n        with: {{app: capture-tool}}\n"
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs))) == []


def test_aliases_resolve_before_validation(tmp_path: Path) -> None:
    jobs = f"  preflight:\n    steps:\n      - uses: actions/checkout@v5\n        with: &consumer-ledger\n          fetch-depth: 0\n          fetch-tags: true\n          persist-credentials: false{WRAPPER_STEP}      - uses: ./.release-devkit/.github/actions/lint-ci\n  publish-prerelease:\n    steps:\n      - uses: actions/checkout@v5\n        with: *consumer-ledger{WRAPPER_STEP}      - uses: ./.release-devkit/.github/actions/publish-prerelease\n"
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs))) == []


def test_bare_checkout_is_rejected(tmp_path: Path) -> None:
    jobs = "  legs:\n    steps:\n      - uses: actions/checkout@v5\n"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("matches no signature" in problem for problem in problems)


def test_publish_stable_requires_persisting_consumer_checkout(tmp_path: Path) -> None:
    jobs = f"  publish-stable:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}      - uses: ./.release-devkit/.github/actions/publish-stable\n"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("consumer-ledger-push" in problem for problem in problems)

    good_jobs = f"  publish-stable:\n    steps:{CONSUMER_LEDGER_PUSH_BLOCK}{WRAPPER_STEP}      - uses: ./.release-devkit/.github/actions/publish-stable\n"
    assert validate_workflow_file(write_workflow(tmp_path, workflow(good_jobs))) == []


def test_preflight_dry_run_uses_plain_consumer_ledger(tmp_path: Path) -> None:
    jobs = (
        f"  preflight:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}"
        "      - uses: ./.release-devkit/.github/actions/publish-stable\n        with:\n          dry-run: true\n"
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs))) == []


def test_push_signature_reserved_for_real_publish_stable(tmp_path: Path) -> None:
    jobs = (
        f"  publish-prerelease:\n    steps:{CONSUMER_LEDGER_PUSH_BLOCK}{WRAPPER_STEP}"
        "      - uses: ./.release-devkit/.github/actions/publish-prerelease\n"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("reserved for real publish-stable" in problem for problem in problems)


def test_verb_job_requires_wrapper_before_the_verb(tmp_path: Path) -> None:
    jobs = f"  publish-prerelease:\n    steps:{CONSUMER_LEDGER_BLOCK}      - uses: ./.release-devkit/.github/actions/publish-prerelease{WRAPPER_STEP}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("no ./.github/actions/checkout-release-devkit step precedes" in problem for problem in problems)


def test_consumer_checkout_must_precede_wrapper(tmp_path: Path) -> None:
    jobs = f"  publish-prerelease:\n    steps:{WRAPPER_STEP}{CONSUMER_LEDGER_BLOCK}      - uses: ./.release-devkit/.github/actions/publish-prerelease\n"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("precedes the checkout-release-devkit step" in problem for problem in problems)


def test_snapshot_signature_is_exact(tmp_path: Path) -> None:
    jobs = "  legs:\n    steps:\n      - uses: actions/checkout@v5\n        with:\n          ref: ${{ github.head_ref || github.ref_name }}\n"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("matches no signature" in problem for problem in problems)


def test_checkout_major_pin_is_enforced(tmp_path: Path) -> None:
    jobs = (
        "  legs:\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          persist-credentials: false\n"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("must be actions/checkout@v5" in problem for problem in problems)


def test_missing_workflow_file_reports_problem(tmp_path: Path) -> None:
    problems = validate_workflow_file(tmp_path / "absent.yml")
    assert any("not found" in problem for problem in problems)


def write_wrapper(tmp_path: Path, steps: str) -> Path:
    wrapper_path = tmp_path / "action.yml"
    wrapper_path.write_text(f"runs:\n  using: composite\n  steps:\n{steps}", encoding="utf-8")
    return wrapper_path


VALID_WRAPPER_STEP = (
    "    - uses: outernet-foundation/release-devkit/.github/actions/checkout-release-devkit@" + "a" * 40 + "\n"
)


def test_valid_wrapper_passes(tmp_path: Path) -> None:
    assert validate_devkit_wrapper(write_wrapper(tmp_path, VALID_WRAPPER_STEP)) == []


def test_wrapper_rejects_short_sha(tmp_path: Path) -> None:
    steps = "    - uses: outernet-foundation/release-devkit/.github/actions/checkout-release-devkit@4712f1e\n"
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("must pin" in problem for problem in problems)


def test_wrapper_rejects_mutable_ref(tmp_path: Path) -> None:
    steps = "    - uses: outernet-foundation/release-devkit/.github/actions/checkout-release-devkit@main\n"
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("must pin" in problem for problem in problems)


def test_wrapper_rejects_extra_steps(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEP + "    - run: echo hello\n"
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("exactly one step" in problem for problem in problems)


def test_wrapper_rejects_wrong_repository(tmp_path: Path) -> None:
    steps = "    - uses: someone-else/release-devkit/.github/actions/checkout-release-devkit@" + "a" * 40 + "\n"
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("must pin" in problem for problem in problems)
