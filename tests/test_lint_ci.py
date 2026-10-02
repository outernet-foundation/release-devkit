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
      - uses: ./.github/actions/setup-release-devkit
"""

GET_APP_VERSION_RUN = (
    '      - run: echo "version=$(uv run --project "$RUNNER_TEMP/release-devkit"'
    ' --locked --no-dev get-app-version --app capture-tool)" >> "$GITHUB_OUTPUT"\n'
)

LINT_CI_RUN = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev lint-ci\n'

PUBLISH_PRERELEASE_RUN = (
    '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev publish-prerelease\n'
)

PUBLISH_STABLE_RUN = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev publish-stable\n'

PUBLISH_STABLE_DRY_RUN = (
    '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev publish-stable --dry-run\n'
)

PUBLISH_STABLE_ENV = (
    "        env:\n"
    "          GH_TOKEN: ${{ github.token }}\n"
    "          CI_REGISTRY_USERNAME: ${{ github.actor }}\n"
    "          CI_REGISTRY_TOKEN: ${{ github.token }}\n"
)


def workflow(jobs: str) -> str:
    return f"jobs:\n{jobs}"


def test_valid_verb_job_has_no_problems(tmp_path: Path) -> None:
    jobs = f"  preflight:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{GET_APP_VERSION_RUN}"
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs))) == []


def test_aliases_resolve_before_validation(tmp_path: Path) -> None:
    jobs = (
        "  preflight:\n    steps:\n      - uses: actions/checkout@v5\n        with: &consumer-ledger\n"
        "          fetch-depth: 0\n          fetch-tags: true\n          persist-credentials: false"
        f"{WRAPPER_STEP}{LINT_CI_RUN}  publish-prerelease:\n    steps:\n"
        "      - uses: actions/checkout@v5\n        with: *consumer-ledger"
        f"{WRAPPER_STEP}{PUBLISH_PRERELEASE_RUN}"
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs))) == []


def test_bare_checkout_is_rejected(tmp_path: Path) -> None:
    jobs = "  legs:\n    steps:\n      - uses: actions/checkout@v5\n"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("matches no signature" in problem for problem in problems)


def test_publish_stable_requires_persisting_consumer_checkout(tmp_path: Path) -> None:
    jobs = f"  publish-stable:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{PUBLISH_STABLE_RUN}{PUBLISH_STABLE_ENV}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("consumer-ledger-push" in problem for problem in problems)

    good_jobs = (
        f"  publish-stable:\n    steps:{CONSUMER_LEDGER_PUSH_BLOCK}{WRAPPER_STEP}{PUBLISH_STABLE_RUN}"
        f"{PUBLISH_STABLE_ENV}"
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(good_jobs))) == []


def test_preflight_dry_run_uses_plain_consumer_ledger(tmp_path: Path) -> None:
    jobs = f"  preflight:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{PUBLISH_STABLE_DRY_RUN}{PUBLISH_STABLE_ENV}"
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs))) == []


def test_push_signature_reserved_for_real_publish_stable(tmp_path: Path) -> None:
    jobs = f"  publish-prerelease:\n    steps:{CONSUMER_LEDGER_PUSH_BLOCK}{WRAPPER_STEP}{PUBLISH_PRERELEASE_RUN}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("reserved for real publish-stable" in problem for problem in problems)


def test_verb_job_requires_wrapper_before_the_verb(tmp_path: Path) -> None:
    jobs = f"  publish-prerelease:\n    steps:{CONSUMER_LEDGER_BLOCK}{PUBLISH_PRERELEASE_RUN}{WRAPPER_STEP}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("no ./.github/actions/setup-release-devkit step precedes" in problem for problem in problems)


def test_consumer_checkout_must_precede_wrapper(tmp_path: Path) -> None:
    jobs = f"  publish-prerelease:\n    steps:{WRAPPER_STEP}{CONSUMER_LEDGER_BLOCK}{PUBLISH_PRERELEASE_RUN}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("precedes the setup-release-devkit step" in problem for problem in problems)


def test_publish_stable_requires_canonical_env(tmp_path: Path) -> None:
    jobs = f"  publish-stable:\n    steps:{CONSUMER_LEDGER_PUSH_BLOCK}{WRAPPER_STEP}{PUBLISH_STABLE_RUN}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("publish-stable requires env GH_TOKEN" in problem for problem in problems)
    assert any("publish-stable requires env CI_REGISTRY_USERNAME" in problem for problem in problems)
    assert any("publish-stable requires env CI_REGISTRY_TOKEN" in problem for problem in problems)


def test_directory_invocation_is_rejected(tmp_path: Path) -> None:
    step = '      - run: uv run --directory "$RUNNER_TEMP/release-devkit" --locked --no-dev lint-ci\n'
    jobs = f"  preflight:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{step}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("without a canonical" in problem for problem in problems)


def test_unknown_verb_is_rejected(tmp_path: Path) -> None:
    step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev create-release\n'
    jobs = f"  preflight:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{step}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("without a canonical" in problem for problem in problems)


def test_unlocked_invocation_is_rejected(tmp_path: Path) -> None:
    step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --no-dev lint-ci\n'
    jobs = f"  preflight:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{step}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("without a canonical" in problem for problem in problems)


def test_rejected_verb_flags_are_flagged(tmp_path: Path) -> None:
    step = (
        '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev publish-prerelease --run-id 42\n'
    )
    jobs = f"  publish-prerelease:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{step}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("carries rejected arguments" in problem for problem in problems)


def test_get_app_version_requires_app(tmp_path: Path) -> None:
    step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev get-app-version\n'
    jobs = f"  preflight:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{step}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("carries rejected arguments" in problem for problem in problems)


def test_dead_composite_action_uses_are_rejected(tmp_path: Path) -> None:
    step = "      - uses: ./.release-devkit/.github/actions/publish-prerelease\n"
    jobs = f"  publish-prerelease:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{step}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("dead composite-action model" in problem for problem in problems)

    old_wrapper = "      - uses: ./.github/actions/checkout-release-devkit\n"
    old_jobs = f"  publish-prerelease:\n    steps:{CONSUMER_LEDGER_BLOCK}{old_wrapper}{PUBLISH_PRERELEASE_RUN}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(old_jobs)))
    assert any("dead composite-action model" in problem for problem in problems)


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


VALID_WRAPPER_STEPS = (
    "    - uses: astral-sh/setup-uv@v7\n"
    "      with:\n"
    "        enable-cache: true\n"
    "    - shell: bash\n"
    "      run: >-\n"
    "        git clone https://github.com/outernet-foundation/release-devkit.git"
    ' "$RUNNER_TEMP/release-devkit"\n'
    '        && git -C "$RUNNER_TEMP/release-devkit" checkout ' + "a" * 40 + "\n"
)


def test_valid_wrapper_passes(tmp_path: Path) -> None:
    assert validate_devkit_wrapper(write_wrapper(tmp_path, VALID_WRAPPER_STEPS)) == []


def test_wrapper_rejects_short_sha(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEPS.replace("a" * 40, "4712f1e")
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("clone" in problem for problem in problems)


def test_wrapper_rejects_mutable_ref(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEPS.replace("a" * 40, "main")
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("clone" in problem for problem in problems)


def test_wrapper_rejects_extra_steps(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEPS + "    - run: echo hello\n"
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("exactly two steps" in problem for problem in problems)


def test_wrapper_rejects_single_step(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEPS.split("    - shell: bash\n")[0]
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("exactly two steps" in problem for problem in problems)


def test_wrapper_rejects_wrong_repository(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEPS.replace(
        "https://github.com/outernet-foundation/release-devkit.git",
        "https://github.com/someone-else/release-devkit.git",
    )
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("clone" in problem for problem in problems)


def test_wrapper_rejects_missing_enable_cache(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEPS.replace("      with:\n        enable-cache: true\n", "")
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("enable-cache" in problem for problem in problems)


def test_wrapper_rejects_missing_checkout(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEPS.replace('\n        && git -C "$RUNNER_TEMP/release-devkit" checkout ' + "a" * 40, "")
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("clone" in problem for problem in problems)


def test_wrapper_rejects_missing_shell(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEPS.replace("    - shell: bash\n      run: >-\n", "    - run: >-\n")
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("shell: bash" in problem for problem in problems)
