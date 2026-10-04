from pathlib import Path

from release_devkit.lint_workflows import validate_devkit_wrapper, validate_workflow_file


def write_workflow(tmp_path: Path, text: str, name: str = "integrate.yml") -> Path:
    workflow_path = tmp_path / name
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

LINT_CI_RUN = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev lint-workflows\n'

PUBLISH_PRERELEASE_RUN = (
    '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev publish-prerelease\n'
)

PUBLISH_STABLE_RUN = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev release\n'

VALIDATE_PLAN_RUN = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev validate-release-plan\n'

PUBLISH_STABLE_ENV = "        env:\n          GITHUB_TOKEN: ${{ github.token }}\n"

MERGE_BOT_CHECKOUT_BLOCK = (
    "      - uses: actions/checkout@v5\n"
    "        with:\n"
    "          ref: ${{ github.event.pull_request.head.sha || github.event.workflow_run.head_sha }}\n"
    "          fetch-depth: 0\n"
    "          persist-credentials: false\n"
)

MINT_STEP = (
    "      - uses: actions/create-github-app-token@v3\n"
    "        id: mint\n"
    "        with:\n"
    "          app-id: ${{ vars.MERGE_BOT_APP_ID }}\n"
    "          private-key: ${{ secrets.MERGE_BOT_APP_PRIVATE_KEY }}\n"
)

MERGE_GATE_RUN = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev merge-gate\n'

MERGE_GATE_ENV = (
    "        env:\n"
    "          GITHUB_TOKEN: ${{ steps.mint.outputs.token }}\n"
    "          HEAD_SHA: ${{ github.event.pull_request.head.sha || github.event.workflow_run.head_sha }}\n"
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
    jobs = f"  release:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{PUBLISH_STABLE_RUN}{PUBLISH_STABLE_ENV}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("consumer-ledger-push" in problem for problem in problems)

    good_jobs = (
        f"  release:\n    steps:{CONSUMER_LEDGER_PUSH_BLOCK}{WRAPPER_STEP}{PUBLISH_STABLE_RUN}"
        f"{PUBLISH_STABLE_ENV}"
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(good_jobs))) == []


def test_publish_stable_rejects_the_dead_dry_run_flag(tmp_path: Path) -> None:
    step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev release --dry-run\n'
    jobs = f"  preflight:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{step}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("carries rejected arguments" in problem for problem in problems)


def test_push_signature_reserved_for_real_publish_stable(tmp_path: Path) -> None:
    jobs = f"  publish-prerelease:\n    steps:{CONSUMER_LEDGER_PUSH_BLOCK}{WRAPPER_STEP}{PUBLISH_PRERELEASE_RUN}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("reserved for real release" in problem for problem in problems)


def test_verb_job_requires_wrapper_before_the_verb(tmp_path: Path) -> None:
    jobs = f"  publish-prerelease:\n    steps:{CONSUMER_LEDGER_BLOCK}{PUBLISH_PRERELEASE_RUN}{WRAPPER_STEP}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("no ./.github/actions/setup-release-devkit step precedes" in problem for problem in problems)


def test_consumer_checkout_must_precede_wrapper(tmp_path: Path) -> None:
    jobs = f"  publish-prerelease:\n    steps:{WRAPPER_STEP}{CONSUMER_LEDGER_BLOCK}{PUBLISH_PRERELEASE_RUN}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("precedes the setup-release-devkit step" in problem for problem in problems)


def test_publish_stable_requires_canonical_env(tmp_path: Path) -> None:
    jobs = f"  release:\n    steps:{CONSUMER_LEDGER_PUSH_BLOCK}{WRAPPER_STEP}{PUBLISH_STABLE_RUN}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("release requires env GITHUB_TOKEN" in problem for problem in problems)


def test_directory_invocation_is_rejected(tmp_path: Path) -> None:
    step = '      - run: uv run --directory "$RUNNER_TEMP/release-devkit" --locked --no-dev lint-workflows\n'
    jobs = f"  preflight:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{step}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("without a canonical" in problem for problem in problems)


def test_unknown_verb_is_rejected(tmp_path: Path) -> None:
    step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev create-release\n'
    jobs = f"  preflight:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{step}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("without a canonical" in problem for problem in problems)


def test_unlocked_invocation_is_rejected(tmp_path: Path) -> None:
    step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --no-dev lint-workflows\n'
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


def test_validate_plan_rejects_flags(tmp_path: Path) -> None:
    step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev validate-release-plan --foo\n'
    jobs = f"  validate-release-plan:\n    steps:{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{step}"
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


def merge_gate_document(steps: str) -> str:
    return (
        "name: Merge gate\n"
        "on:\n"
        "  pull_request:\n"
        "    branches: [dev]\n"
        "    types: [labeled]\n"
        "  workflow_run:\n"
        "    workflows: [Integrate]\n"
        "    types: [completed]\n"
        "concurrency:\n"
        "  group: merge-gate-${{ github.event.pull_request.number || github.event.workflow_run.head_branch }}\n"
        "jobs:\n"
        "  merge-gate:\n"
        "    if: github.event.label.name == 'ready-to-merge' || (github.event_name == 'workflow_run'"
        " && github.event.workflow_run.conclusion == 'success')\n"
        f"    steps:\n{steps}"
    )


def test_valid_merge_gate_job_has_no_problems(tmp_path: Path) -> None:
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    path = write_workflow(tmp_path, merge_gate_document(steps), name="merge-gate.yml")
    assert validate_workflow_file(path) == []


def test_merge_gate_requires_merge_bot_checkout(tmp_path: Path) -> None:
    steps = f"{CONSUMER_LEDGER_BLOCK}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    path = write_workflow(tmp_path, merge_gate_document(steps), name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("no merge-bot checkout precedes" in problem for problem in problems)


def test_merge_bot_checkout_reserved_for_merge_gate_jobs(tmp_path: Path) -> None:
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{PUBLISH_PRERELEASE_RUN}"
    jobs = f"jobs:\n  publish-prerelease:\n    steps:\n{steps}"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("merge-bot checkout is reserved" in problem for problem in problems)


def test_merge_gate_requires_canonical_mint_step(tmp_path: Path) -> None:
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    path = write_workflow(tmp_path, merge_gate_document(steps), name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("requires a canonical actions/create-github-app-token@v3 mint step" in problem for problem in problems)


def test_merge_gate_rejects_non_canonical_mint_inputs(tmp_path: Path) -> None:
    renamed_app_step = MINT_STEP.replace("app-id: ${{ vars.MERGE_BOT_APP_ID }}", "app-id: 123456")
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{renamed_app_step}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    path = write_workflow(tmp_path, merge_gate_document(steps), name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("canonical mint step" in problem for problem in problems)


def test_merge_gate_requires_minted_token_env(tmp_path: Path) -> None:
    wrong_env = MERGE_GATE_ENV.replace("${{ steps.mint.outputs.token }}", "${{ github.token }}")
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{wrong_env}"
    path = write_workflow(tmp_path, merge_gate_document(steps), name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("merge-gate requires env GITHUB_TOKEN" in problem for problem in problems)


def test_merge_gate_requires_the_dispatch_head_sha_env(tmp_path: Path) -> None:
    missing_env = MERGE_GATE_ENV.replace("          HEAD_SHA: ${{ github.event.pull_request.head.sha || github.event.workflow_run.head_sha }}\n", "")
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{missing_env}"
    path = write_workflow(tmp_path, merge_gate_document(steps), name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("merge-gate requires env HEAD_SHA" in problem for problem in problems)


def test_merge_gate_requires_head_sha_env(tmp_path: Path) -> None:
    missing_env = MERGE_GATE_ENV.replace("          HEAD_SHA: ${{ github.event.workflow_run.head_sha }}\n", "")
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{missing_env}"
    path = write_workflow(tmp_path, merge_gate_document(steps), name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("merge-gate requires env HEAD_SHA" in problem for problem in problems)


def test_merge_gate_workflow_requires_labeled_trigger_only(tmp_path: Path) -> None:
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    document = merge_gate_document(steps).replace("    types: [labeled]\n", "    types: [labeled, opened]\n")
    path = write_workflow(tmp_path, document, name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("must trigger on pull_request to dev" in problem for problem in problems)


def test_merge_gate_workflow_requires_dev_branch_scope(tmp_path: Path) -> None:
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    document = merge_gate_document(steps).replace("    branches: [dev]\n", "")
    path = write_workflow(tmp_path, document, name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("must trigger on pull_request to dev" in problem for problem in problems)


def test_merge_gate_workflow_requires_workflow_run_wake(tmp_path: Path) -> None:
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    document = merge_gate_document(steps).replace(
        "  workflow_run:\n    workflows: [Integrate]\n    types: [completed]\n", ""
    )
    path = write_workflow(tmp_path, document, name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("must trigger on workflow_run from Integrate" in problem for problem in problems)


def test_merge_gate_workflow_pins_the_integrate_workflow_name(tmp_path: Path) -> None:
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    document = merge_gate_document(steps).replace("workflows: [Integrate]", "workflows: [CI]")
    path = write_workflow(tmp_path, document, name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("must trigger on workflow_run from Integrate" in problem for problem in problems)


def test_merge_gate_workflow_requires_the_per_pr_concurrency_group(tmp_path: Path) -> None:
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    document = merge_gate_document(steps).replace(
        "group: merge-gate-${{ github.event.pull_request.number || github.event.workflow_run.head_branch }}",
        "group: merge-gate",
    )
    path = write_workflow(tmp_path, document, name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("concurrency group must be" in problem for problem in problems)


def test_merge_gate_workflow_refuses_cancel_in_progress(tmp_path: Path) -> None:
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    document = merge_gate_document(steps).replace("head_branch }}\n", "head_branch }}\n  cancel-in-progress: true\n")
    path = write_workflow(tmp_path, document, name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("cancel-in-progress" in problem for problem in problems)


def test_merge_gate_workflow_jobs_require_the_dual_wake_gate(tmp_path: Path) -> None:
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    document = merge_gate_document(steps).replace(
        "    if: github.event.label.name == 'ready-to-merge' || (github.event_name == 'workflow_run'"
        " && github.event.workflow_run.conclusion == 'success')\n",
        "",
    )
    path = write_workflow(tmp_path, document, name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("must gate on" in problem for problem in problems)


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
