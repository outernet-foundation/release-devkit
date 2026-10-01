from pathlib import Path

from release_devkit.lint_ci import validate_workflow_file


def write_workflow(tmp_path: Path, text: str) -> Path:
    workflow_path = tmp_path / "ci-cd.yml"
    workflow_path.write_text(text, encoding="utf-8")
    return workflow_path


PIN = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

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

HOUSEMATE_BLOCK = """
      - uses: actions/checkout@v5
        with:
          repository: outernet-foundation/release-devkit
          ref: ${{ env.RELEASE_DEVKIT_SHA }}
          path: .release-devkit
          persist-credentials: false
"""


def workflow(jobs: str) -> str:
    return f"env:\n  RELEASE_DEVKIT_SHA: {PIN}\njobs:\n{jobs}"


def test_valid_verb_job_has_no_problems(tmp_path: Path) -> None:
    jobs = f"  preflight:\n    steps:{CONSUMER_LEDGER_BLOCK}{HOUSEMATE_BLOCK}      - uses: ./.release-devkit/.github/actions/get-app-version\n        with: {{app: capture-tool}}\n"
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs))) == []


def test_aliases_resolve_before_validation(tmp_path: Path) -> None:
    jobs = f"  preflight:\n    steps:\n      - uses: actions/checkout@v5\n        with: &consumer-ledger\n          fetch-depth: 0\n          fetch-tags: true\n          persist-credentials: false{HOUSEMATE_BLOCK}      - uses: ./.release-devkit/.github/actions/lint-ci\n  publish-dev:\n    steps:\n      - uses: actions/checkout@v5\n        with: *consumer-ledger{HOUSEMATE_BLOCK}      - uses: ./.release-devkit/.github/actions/publish-dev\n"
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs))) == []


def test_bare_checkout_is_rejected(tmp_path: Path) -> None:
    jobs = "  legs:\n    steps:\n      - uses: actions/checkout@v5\n"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("matches no signature" in problem for problem in problems)


def test_publish_stable_requires_persisting_consumer_checkout(tmp_path: Path) -> None:
    jobs = f"  publish-stable:\n    steps:{CONSUMER_LEDGER_BLOCK}{HOUSEMATE_BLOCK}      - uses: ./.release-devkit/.github/actions/publish-stable\n"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("consumer-ledger-push" in problem for problem in problems)

    good_jobs = f"  publish-stable:\n    steps:{CONSUMER_LEDGER_PUSH_BLOCK}{HOUSEMATE_BLOCK}      - uses: ./.release-devkit/.github/actions/publish-stable\n"
    assert validate_workflow_file(write_workflow(tmp_path, workflow(good_jobs))) == []


def test_preflight_dry_run_uses_plain_consumer_ledger(tmp_path: Path) -> None:
    jobs = (
        f"  preflight:\n    steps:{CONSUMER_LEDGER_BLOCK}{HOUSEMATE_BLOCK}"
        "      - uses: ./.release-devkit/.github/actions/publish-stable\n        with:\n          dry-run: true\n"
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs))) == []


def test_push_signature_reserved_for_real_publish_stable(tmp_path: Path) -> None:
    jobs = f"  publish-dev:\n    steps:{CONSUMER_LEDGER_PUSH_BLOCK}{HOUSEMATE_BLOCK}      - uses: ./.release-devkit/.github/actions/publish-dev\n"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("reserved for real publish-stable" in problem for problem in problems)


def test_verb_job_requires_housemate_before_the_verb(tmp_path: Path) -> None:
    jobs = f"  publish-dev:\n    steps:{CONSUMER_LEDGER_BLOCK}      - uses: ./.release-devkit/.github/actions/publish-dev{HOUSEMATE_BLOCK}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("no housemate checkout precedes" in problem for problem in problems)


def test_consumer_checkout_must_precede_housemate(tmp_path: Path) -> None:
    jobs = f"  publish-dev:\n    steps:{HOUSEMATE_BLOCK}{CONSUMER_LEDGER_BLOCK}      - uses: ./.release-devkit/.github/actions/publish-dev\n"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("precedes the housemate" in problem for problem in problems)


def test_snapshot_signature_is_exact(tmp_path: Path) -> None:
    jobs = "  legs:\n    steps:\n      - uses: actions/checkout@v5\n        with:\n          ref: ${{ github.head_ref || github.ref_name }}\n"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("matches no signature" in problem for problem in problems)


def test_devkit_pin_must_be_full_sha_at_workflow_level(tmp_path: Path) -> None:
    text = "env:\n  RELEASE_DEVKIT_SHA: 4712f1e\njobs:\n  legs:\n    steps: []\n"
    problems = validate_workflow_file(write_workflow(tmp_path, text))
    assert any("RELEASE_DEVKIT_SHA" in problem for problem in problems)

    missing = "jobs:\n  legs:\n    steps: []\n"
    problems = validate_workflow_file(write_workflow(tmp_path, missing))
    assert any("RELEASE_DEVKIT_SHA" in problem for problem in problems)


def test_checkout_major_pin_is_enforced(tmp_path: Path) -> None:
    jobs = (
        "  legs:\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          persist-credentials: false\n"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("must be actions/checkout@v5" in problem for problem in problems)


def test_missing_workflow_file_reports_problem(tmp_path: Path) -> None:
    problems = validate_workflow_file(tmp_path / "absent.yml")
    assert any("not found" in problem for problem in problems)
