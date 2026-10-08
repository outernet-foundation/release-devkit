import tomllib
from pathlib import Path

import pytest

from release_devkit.verbs.lint_workflows import (
    RELEASE_VERB,
    VERB_SPECS,
    WRAPPER_COMMIT_ENV_VAR,
    default_workflows,
    validate_devkit_wrapper,
    validate_workflow_file,
)


def write_workflow(tmp_path: Path, text: str, name: str = "workflow.yml") -> Path:
    workflow_path = tmp_path / name
    workflow_path.write_text(text, encoding="utf-8")
    return workflow_path


CHECKOUT_BLOCK = """
      - uses: actions/checkout@v5
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          persist-credentials: false
"""

CHECKOUT_WITH_TAGS_BLOCK = """
      - uses: actions/checkout@v5
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
          fetch-tags: true
          persist-credentials: false
"""

CHECKOUT_WITH_TAGS_PUSH_BLOCK = """
      - uses: actions/checkout@v5
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
          fetch-tags: true
          persist-credentials: true
"""

RELEASE_CHECKOUT_WITH_TAGS_BLOCK = """
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
          fetch-tags: true
          persist-credentials: false
"""

RELEASE_CHECKOUT_WITH_TAGS_PUSH_BLOCK = """
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
          fetch-tags: true
          persist-credentials: true
"""

SETUP_UV_RESTORE_STEP = """
      - uses: astral-sh/setup-uv@v7
        with:
          enable-cache: true
          save-cache: "false"
"""

SAVER_SETUP_UV_STEP = """
      - uses: astral-sh/setup-uv@v7
        with:
          enable-cache: true
          save-cache: "true"
"""

WRAPPER_STEP = """
      - uses: ./.github/actions/setup-release-devkit
"""

GET_APP_VERSION_RUN = (
    "      - id: version\n"
    '        run: uv run --project "$RUNNER_TEMP/release-devkit"'
    " --locked --no-dev get-app-version --app capture-tool\n"
)

LINT_WORKFLOWS_RUN = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev lint-workflows\n'

RELEASE_PR_RUN = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev release --channel pr\n'

RELEASE_DEV_RUN = (
    '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev release --channel dev\n'
)

RELEASE_STABLE_RUN = (
    '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev release --channel stable\n'
)

VALIDATE_RELEASE_PLAN_RUN = (
    '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev validate-release-plan\n'
)

RELEASE_ENV = "        env:\n          GITHUB_TOKEN: ${{ github.token }}\n"

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

MERGE_GATE_RUN = (
    '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev'
    " merge-gate --head-sha ${{ github.event.pull_request.head.sha || github.event.workflow_run.head_sha }}\n"
)

MERGE_GATE_ENV = "        env:\n          GITHUB_TOKEN: ${{ steps.mint.outputs.token }}\n"

PR_DRAFT_JOB = (
    f"  update-pr-draft-release:\n    if: github.event.pull_request\n    needs: [validate-release-plan]\n"
    f"    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_PR_RUN}{RELEASE_ENV}"
)

NUGET_LOGIN_STEP = (
    "      - uses: NuGet/login@v1\n        id: nuget-login\n        with:\n          user: ${{ secrets.NUGET_USER }}\n"
)

RELEASE_NUGET_ENV = (
    "        env:\n"
    "          GITHUB_TOKEN: ${{ github.token }}\n"
    "          NUGET_API_KEY: ${{ steps.nuget-login.outputs.NUGET_API_KEY }}\n"
)


def workflow(*job_blocks: str) -> str:
    return "jobs:\n" + "".join(job_blocks)


def job_block(job_name: str, steps: str, needs: list[str] | None = None) -> str:
    needs_block = f"    needs: [{', '.join(needs)}]\n" if needs is not None else ""
    return f"  {job_name}:\n{needs_block}    steps:{steps}"


def test_verb_spec_table_matches_the_console_scripts() -> None:
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    scripts: dict[str, str] = pyproject["project"]["scripts"]
    assert sorted([*VERB_SPECS, RELEASE_VERB]) == sorted(scripts)


def test_valid_verb_job_has_no_problems(tmp_path: Path) -> None:
    jobs = job_block(
        "prerelease",
        f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_DEV_RUN}{RELEASE_ENV}",
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs))) == []


def test_nuget_delivery_job_with_mint_step_has_no_problems(tmp_path: Path) -> None:
    jobs = job_block(
        "prerelease",
        f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{NUGET_LOGIN_STEP}{RELEASE_DEV_RUN}"
        f"{RELEASE_NUGET_ENV}",
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs)), nuget=True) == []


def test_nuget_delivery_job_requires_the_mint_step(tmp_path: Path) -> None:
    jobs = job_block(
        "prerelease",
        f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_DEV_RUN}{RELEASE_NUGET_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)), nuget=True)
    assert any("require a canonical NuGet/login@v1 mint step" in problem for problem in problems)


def test_nuget_delivery_job_rejects_mint_step_outside_the_window(tmp_path: Path) -> None:
    jobs = job_block(
        "prerelease",
        f"{CHECKOUT_WITH_TAGS_BLOCK}{NUGET_LOGIN_STEP}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_DEV_RUN}"
        f"{RELEASE_NUGET_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)), nuget=True)
    assert any("between the wrapper and the verb" in problem for problem in problems)


def test_non_nuget_repo_rejects_the_mint_step(tmp_path: Path) -> None:
    jobs = job_block(
        "prerelease",
        f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{NUGET_LOGIN_STEP}{RELEASE_DEV_RUN}"
        f"{RELEASE_NUGET_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)), nuget=False)
    assert any("reserved for the delivery jobs" in problem for problem in problems)
    assert any("must not carry NUGET_API_KEY env" in problem for problem in problems)


def test_nuget_job_rejects_non_canonical_login_inputs(tmp_path: Path) -> None:
    hard_coded_user = NUGET_LOGIN_STEP.replace("${{ secrets.NUGET_USER }}", "some-profile")
    jobs = job_block(
        "prerelease",
        f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{hard_coded_user}{RELEASE_DEV_RUN}"
        f"{RELEASE_NUGET_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)), nuget=True)
    assert any("must be the canonical mint step" in problem for problem in problems)


def test_nuget_verb_env_source_must_be_the_minted_key(tmp_path: Path) -> None:
    stale_secret_source = RELEASE_NUGET_ENV.replace("steps.nuget-login.outputs.NUGET_API_KEY", "secrets.NUGET_API_KEY")
    jobs = job_block(
        "prerelease",
        f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{NUGET_LOGIN_STEP}{RELEASE_DEV_RUN}"
        f"{stale_secret_source}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)), nuget=True)
    assert any("requires env NUGET_API_KEY" in problem for problem in problems)


def test_environment_key_is_rejected(tmp_path: Path) -> None:
    jobs = (
        f"  prerelease:\n    environment: release\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}"
        f"{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_DEV_RUN}{RELEASE_NUGET_ENV}"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)), nuget=True)
    assert any("environment: key is forbidden" in problem for problem in problems)


def test_get_app_version_job_uses_the_tags_checkout(tmp_path: Path) -> None:
    jobs = job_block(
        "validate-release-plan",
        f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{GET_APP_VERSION_RUN}"
        f"{VALIDATE_RELEASE_PLAN_RUN}",
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs))) == []


def test_aliases_resolve_before_validation(tmp_path: Path) -> None:
    gated_lint_run = LINT_WORKFLOWS_RUN
    jobs = (
        "  lint-workflows:\n    steps:\n      - &checkout\n"
        "        uses: actions/checkout@v5\n"
        "        with:\n"
        "          ref: ${{ github.event.pull_request.head.sha }}\n"
        "          persist-credentials: false\n"
        f"{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        "  second:\n    steps:\n      - *checkout\n"
        f"{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{gated_lint_run}"
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs))) == []


def test_bare_checkout_is_rejected(tmp_path: Path) -> None:
    jobs = "  legs:\n    steps:\n      - uses: actions/checkout@v5\n        with:\n          fetch-depth: 0\n"
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("matches no signature" in problem for problem in problems)


def test_untagged_ledger_checkout_is_rejected(tmp_path: Path) -> None:
    jobs = (
        "  validate-release-plan:\n    steps:\n      - uses: actions/checkout@v5\n        with:\n"
        "          fetch-depth: 0\n          fetch-tags: true\n          persist-credentials: false\n"
        f"{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{VALIDATE_RELEASE_PLAN_RUN}"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("no checkout-with-tags checkout precedes" in problem for problem in problems)


def test_stable_release_requires_persisting_consumer_checkout(tmp_path: Path) -> None:
    jobs = job_block(
        "release",
        f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_STABLE_RUN}{RELEASE_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("no checkout-with-tags-push checkout precedes" in problem for problem in problems)

    good_jobs = job_block(
        "release",
        f"{CHECKOUT_WITH_TAGS_PUSH_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_STABLE_RUN}{RELEASE_ENV}",
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(good_jobs))) == []


def test_implicit_persisting_checkout_is_rejected(tmp_path: Path) -> None:
    implicit = """
      - uses: actions/checkout@v5
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
          fetch-tags: true
"""
    jobs = job_block("release", f"{implicit}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_STABLE_RUN}{RELEASE_ENV}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("matches no signature" in problem for problem in problems)


def test_push_signature_reserved_for_stable_channel_jobs(tmp_path: Path) -> None:
    jobs = job_block(
        "prerelease",
        f"{CHECKOUT_WITH_TAGS_PUSH_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_DEV_RUN}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("reserved for stable-channel release jobs" in problem for problem in problems)


def test_verb_job_requires_wrapper_before_the_verb(tmp_path: Path) -> None:
    jobs = job_block("prerelease", f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{RELEASE_DEV_RUN}{WRAPPER_STEP}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("no ./.github/actions/setup-release-devkit step precedes" in problem for problem in problems)


def test_duplicate_wrapper_steps_are_rejected(tmp_path: Path) -> None:
    jobs = job_block(
        "prerelease",
        f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{WRAPPER_STEP}{RELEASE_DEV_RUN}{RELEASE_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("exactly one ./.github/actions/setup-release-devkit step" in problem for problem in problems)


def test_consumer_checkout_must_precede_wrapper(tmp_path: Path) -> None:
    jobs = job_block(
        "prerelease",
        f"{WRAPPER_STEP}{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{RELEASE_DEV_RUN}{RELEASE_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("precedes the setup-release-devkit step" in problem for problem in problems)


def test_verb_job_requires_canonical_setup_uv_before_the_wrapper(tmp_path: Path) -> None:
    jobs = job_block("prerelease", f"{CHECKOUT_WITH_TAGS_BLOCK}{WRAPPER_STEP}{RELEASE_DEV_RUN}{RELEASE_ENV}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("no canonical astral-sh/setup-uv@v7 step" in problem for problem in problems)


def test_setup_uv_without_explicit_save_cache_is_not_canonical(tmp_path: Path) -> None:
    loose_uv = "      - uses: astral-sh/setup-uv@v7\n        with:\n          enable-cache: true\n"
    jobs = job_block("prerelease", f"{CHECKOUT_WITH_TAGS_BLOCK}{loose_uv}{WRAPPER_STEP}{RELEASE_DEV_RUN}{RELEASE_ENV}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("no canonical astral-sh/setup-uv@v7 step" in problem for problem in problems)


def test_stable_release_requires_canonical_env(tmp_path: Path) -> None:
    jobs = job_block(
        "release", f"{CHECKOUT_WITH_TAGS_PUSH_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_STABLE_RUN}"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("release --channel stable requires env GITHUB_TOKEN" in problem for problem in problems)


def test_directory_invocation_is_rejected(tmp_path: Path) -> None:
    step = '      - run: uv run --directory "$RUNNER_TEMP/release-devkit" --locked --no-dev lint-workflows\n'
    jobs = job_block("lint-workflows", f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("without a canonical" in problem for problem in problems)


def test_unlocked_invocation_is_rejected(tmp_path: Path) -> None:
    step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --no-dev lint-workflows\n'
    jobs = job_block("lint-workflows", f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("without a canonical" in problem for problem in problems)


def test_rejected_channel_args_are_flagged(tmp_path: Path) -> None:
    step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev release --channel bogus\n'
    jobs = job_block("prerelease", f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("carries rejected arguments" in problem for problem in problems)


def test_bare_release_is_rejected(tmp_path: Path) -> None:
    step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev release\n'
    jobs = job_block("release", f"{CHECKOUT_WITH_TAGS_PUSH_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("carries rejected arguments" in problem for problem in problems)


def test_old_verb_spellings_are_rejected(tmp_path: Path) -> None:
    prerelease_step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev prerelease\n'
    jobs = job_block("prerelease", f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{prerelease_step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("without a canonical" in problem for problem in problems)

    update_pr_draft_step = (
        '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev update-pr-draft-release\n'
    )
    jobs = job_block(
        "update-pr-draft-release",
        f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{update_pr_draft_step}{RELEASE_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("without a canonical" in problem for problem in problems)


def test_flag_pass_through_contract_is_rejected(tmp_path: Path) -> None:
    step = (
        '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev release --channel dev'
        " --repository ${{ github.repository }}"
        " --actor ${{ github.actor }} --workspace ${{ github.workspace }}"
        " --step-summary $GITHUB_STEP_SUMMARY\n"
    )
    jobs = job_block("prerelease", f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("carries rejected arguments" in problem for problem in problems)


def test_release_pr_channel_invocation_is_clean(tmp_path: Path) -> None:
    jobs = job_block(
        "update-pr-draft-release",
        f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_PR_RUN}{RELEASE_ENV}",
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs))) == []


def test_pr_channel_requires_tags_checkout(tmp_path: Path) -> None:
    jobs = job_block(
        "update-pr-draft-release",
        f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_PR_RUN}{RELEASE_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("no checkout-with-tags checkout precedes" in problem for problem in problems)


def test_channel_checkout_matrix(tmp_path: Path) -> None:
    pr_without_tags = job_block(
        "update-pr-draft-release",
        f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_PR_RUN}{RELEASE_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(pr_without_tags)))
    assert any("no checkout-with-tags checkout precedes" in problem for problem in problems)

    stable_without_push = job_block(
        "release", f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_STABLE_RUN}{RELEASE_ENV}"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(stable_without_push)))
    assert any("no checkout-with-tags-push checkout precedes" in problem for problem in problems)


def test_channel_env_matrix(tmp_path: Path) -> None:
    for run in (RELEASE_PR_RUN, RELEASE_DEV_RUN, RELEASE_STABLE_RUN):
        job_name = "release" if run is RELEASE_STABLE_RUN else "prerelease"
        jobs = job_block(job_name, f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{run}")
        problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
        assert any("requires env GITHUB_TOKEN" in problem for problem in problems), run


def test_validate_release_plan_rejects_flags(tmp_path: Path) -> None:
    step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev validate-release-plan --foo\n'
    jobs = job_block("validate-release-plan", f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("carries rejected arguments" in problem for problem in problems)


def test_get_app_version_requires_app(tmp_path: Path) -> None:
    step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev get-app-version\n'
    jobs = job_block("validate-release-plan", f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("carries rejected arguments" in problem for problem in problems)


def test_dead_composite_action_uses_are_rejected(tmp_path: Path) -> None:
    step = "      - uses: ./.release-devkit/.github/actions/prerelease\n"
    jobs = job_block(
        "prerelease",
        f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}{RELEASE_DEV_RUN}{RELEASE_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("dead composite-action model" in problem for problem in problems)

    old_wrapper = "      - uses: ./.github/actions/checkout-release-devkit\n"
    old_jobs = job_block("prerelease", f"{CHECKOUT_WITH_TAGS_BLOCK}{old_wrapper}{RELEASE_DEV_RUN}{RELEASE_ENV}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(old_jobs)))
    assert any("dead composite-action model" in problem for problem in problems)


def test_branch_name_ref_is_rejected(tmp_path: Path) -> None:
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


def test_folded_devkit_invocation_is_rejected(tmp_path: Path) -> None:
    step = (
        "      - run: >-\n"
        '          uv run --project "$RUNNER_TEMP/release-devkit"\n'
        "          --locked --no-dev lint-workflows\n"
    )
    jobs = job_block("lint-workflows", f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("single physical line" in problem for problem in problems)


def test_literal_run_block_is_rejected(tmp_path: Path) -> None:
    step = "      - run: |\n          uv run preflight-python\n          uv run other\n"
    jobs = f"  preflight:\n    needs: [lint-workflows]\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}{step}"
    path = write_workflow(tmp_path, workflow(jobs), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=False)
    assert any("single physical line" in problem for problem in problems)


def test_plain_continuation_run_is_rejected(tmp_path: Path) -> None:
    step = "      - run: uv run compile-check-unity\n          --project thing\n"
    jobs = job_block("legs", f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("single physical line" in problem for problem in problems)


def test_folded_long_command_is_accepted(tmp_path: Path) -> None:
    step = (
        "      - run: >-\n"
        "          uv run ci-build-unity --project ${{ matrix.project-name }}\n"
        "          --platform ${{ matrix.platform }} --cache-key ${{ matrix.cache-key }}\n"
        "          --version-code ${{ needs.validate-release-plan.outputs.version-code }}\n"
        '          --branch "$BRANCH"'
        " --registry ghcr.io/${{ github.repository }}/cache\n"
        "          --builds-registry ghcr.io/${{ github.repository }}/builds\n"
    )
    jobs = job_block("legs", f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert not any("single physical line" in problem for problem in problems)


def test_folded_long_devkit_invocation_is_rejected(tmp_path: Path) -> None:
    step = (
        "      - run: >-\n"
        '          uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev\n'
        "          validate-release-plan --with-a-very-long-flag-that-pushes-this-past-the-threshold-value\n"
    )
    jobs = job_block("legs", f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("devkit verb invocations never fold" in problem for problem in problems)


def test_folded_block_with_blank_line_is_rejected(tmp_path: Path) -> None:
    step = (
        "      - run: >-\n"
        "          uv run ci-build-unity --project ${{ matrix.project-name }}\n"
        "\n"
        "          --platform ${{ matrix.platform }} --cache-key ${{ matrix.cache-key }}\n"
        "          --version-code ${{ needs.validate-release-plan.outputs.version-code }}\n"
        '          --branch "$BRANCH"'
        " --registry ghcr.io/${{ github.repository }}/cache\n"
        "          --builds-registry ghcr.io/${{ github.repository }}/builds\n"
    )
    jobs = job_block("legs", f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("may not contain blank lines" in problem for problem in problems)


def test_folded_block_with_uneven_indent_is_rejected(tmp_path: Path) -> None:
    step = (
        "      - run: >-\n"
        "          uv run ci-build-unity --project ${{ matrix.project-name }}\n"
        "            --platform ${{ matrix.platform }} --cache-key ${{ matrix.cache-key }}\n"
        "          --version-code ${{ needs.validate-release-plan.outputs.version-code }}\n"
        '          --branch "$BRANCH"'
        " --registry ghcr.io/${{ github.repository }}/cache\n"
        "          --builds-registry ghcr.io/${{ github.repository }}/builds\n"
    )
    jobs = job_block("legs", f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs)))
    assert any("must share one indent" in problem for problem in problems)


def integrate_document(jobs: str) -> str:
    return f"jobs:\n{jobs}"


def test_publishing_integrate_requires_the_validate_release_plan_job(tmp_path: Path) -> None:
    jobs = (
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  preflight:\n    needs: [lint-workflows]\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
    )
    path = write_workflow(tmp_path, integrate_document(jobs), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=True)
    assert any("must run the validate-release-plan job" in problem for problem in problems)


def test_publishing_integrate_with_split_jobs_is_clean(tmp_path: Path) -> None:
    jobs = (
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  preflight:\n    needs: [lint-workflows]\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}"
        f"{VALIDATE_RELEASE_PLAN_RUN}"
        f"{PR_DRAFT_JOB}"
    )
    path = write_workflow(tmp_path, integrate_document(jobs), name="integrate.yml")
    assert validate_workflow_file(path, publishing=True) == []


def test_publishing_integrate_requires_the_update_pr_draft_job(tmp_path: Path) -> None:
    jobs = (
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  preflight:\n    needs: [lint-workflows]\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}"
        f"{VALIDATE_RELEASE_PLAN_RUN}"
    )
    path = write_workflow(tmp_path, integrate_document(jobs), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=True)
    assert any("must run the update-pr-draft-release job" in problem for problem in problems)


def test_update_pr_draft_job_requires_the_pull_request_gate(tmp_path: Path) -> None:
    ungated = PR_DRAFT_JOB.replace("    if: github.event.pull_request\n", "")
    jobs = (
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  preflight:\n    needs: [lint-workflows]\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}"
        f"{VALIDATE_RELEASE_PLAN_RUN}"
        f"{ungated}"
    )
    path = write_workflow(tmp_path, integrate_document(jobs), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=True)
    assert any("must gate on if: github.event.pull_request" in problem for problem in problems)


def test_update_pr_draft_job_must_need_validate_release_plan(tmp_path: Path) -> None:
    unneeded = PR_DRAFT_JOB.replace("    needs: [validate-release-plan]\n", "")
    jobs = (
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  preflight:\n    needs: [lint-workflows]\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}"
        f"{VALIDATE_RELEASE_PLAN_RUN}"
        f"{unneeded}"
    )
    path = write_workflow(tmp_path, integrate_document(jobs), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=True)
    assert any("must need validate-release-plan" in problem for problem in problems)


def test_publishing_integrate_with_pr_draft_job_is_clean(tmp_path: Path) -> None:
    jobs = (
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  preflight:\n    needs: [lint-workflows]\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}"
        f"{VALIDATE_RELEASE_PLAN_RUN}"
        f"{PR_DRAFT_JOB}"
    )
    path = write_workflow(tmp_path, integrate_document(jobs), name="integrate.yml")
    assert validate_workflow_file(path, publishing=True) == []


def test_pr_channel_must_live_in_its_own_job(tmp_path: Path) -> None:
    jobs = (
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  preflight:\n    needs: [lint-workflows]\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}"
        f"{VALIDATE_RELEASE_PLAN_RUN}"
        f"  wrong-job:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}"
        f"{RELEASE_PR_RUN}{RELEASE_ENV}"
    )
    path = write_workflow(tmp_path, integrate_document(jobs), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=True)
    assert any("pr channel must run in the 'update-pr-draft-release' job" in problem for problem in problems)


def test_non_publishing_integrate_needs_no_validate_release_plan_job(tmp_path: Path) -> None:
    jobs = (
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  preflight:\n    needs: [lint-workflows]\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
    )
    path = write_workflow(tmp_path, integrate_document(jobs), name="integrate.yml")
    assert validate_workflow_file(path, publishing=False) == []


def test_integrate_requires_the_lint_workflows_job(tmp_path: Path) -> None:
    jobs = f"  preflight:\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
    path = write_workflow(tmp_path, integrate_document(jobs), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=False)
    assert any("must run the lint-workflows job" in problem for problem in problems)


def test_integrate_checkout_requires_the_head_sha_literal(tmp_path: Path) -> None:
    branch_form = (
        "  lint-workflows:\n    steps:\n      - uses: actions/checkout@v5\n        with:\n"
        "          ref: ${{ github.head_ref || github.ref_name }}\n          persist-credentials: false\n"
        f"{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
    )
    path = write_workflow(tmp_path, integrate_document(branch_form), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=False)
    assert any("matches no signature" in problem for problem in problems)


def test_lint_workflows_verb_must_live_in_its_own_job(tmp_path: Path) -> None:
    jobs = f"  preflight:\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
    path = write_workflow(tmp_path, integrate_document(jobs), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=False)
    assert any("must run in the 'lint-workflows' job" in problem for problem in problems)


def test_preflight_must_need_lint_workflows(tmp_path: Path) -> None:
    jobs = (
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  preflight:\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}"
        f"{VALIDATE_RELEASE_PLAN_RUN}"
    )
    path = write_workflow(tmp_path, integrate_document(jobs), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=True)
    assert any("must need" in problem for problem in problems)


def test_lint_workflows_is_a_parallel_root(tmp_path: Path) -> None:
    jobs = (
        f"  validate-release-plan:\n    needs: [lint-workflows]\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}"
        f"{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{VALIDATE_RELEASE_PLAN_RUN}"
        f"  lint-workflows:\n    needs: [validate-release-plan]\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
        f"{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
    )
    path = write_workflow(tmp_path, integrate_document(jobs), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=True)
    assert any("parallel root and must carry no needs" in problem for problem in problems)


def test_integrate_requires_exactly_one_cache_writer(tmp_path: Path) -> None:
    two_writers = (
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  preflight:\n    needs: [lint-workflows]\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}"
        f"{VALIDATE_RELEASE_PLAN_RUN}"
    )
    path = write_workflow(tmp_path, integrate_document(two_writers), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=True)
    assert any("exactly one cache-writing setup-uv step" in problem for problem in problems)

    zero_writers = (
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  preflight:\n    needs: [lint-workflows]\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}"
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}"
        f"{VALIDATE_RELEASE_PLAN_RUN}"
    )
    path = write_workflow(tmp_path, integrate_document(zero_writers), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=True)
    assert any("exactly one cache-writing setup-uv step" in problem for problem in problems)


def test_lint_workflows_is_the_cache_writer_when_preflight_dissolves(tmp_path: Path) -> None:
    jobs = (
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}"
        f"{WRAPPER_STEP}{VALIDATE_RELEASE_PLAN_RUN}"
        f"{PR_DRAFT_JOB}"
    )
    path = write_workflow(tmp_path, integrate_document(jobs), name="integrate.yml")
    assert validate_workflow_file(path, publishing=True) == []

    misplaced = (
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SAVER_SETUP_UV_STEP}"
        f"{WRAPPER_STEP}{VALIDATE_RELEASE_PLAN_RUN}"
        f"{PR_DRAFT_JOB}"
    )
    path = write_workflow(tmp_path, integrate_document(misplaced), name="integrate.yml")
    problems = validate_workflow_file(path, publishing=True)
    assert any("cache-writing setup-uv must live in 'lint-workflows'" in problem for problem in problems)


def test_default_workflows_include_release_iff_the_config_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert default_workflows()[1].name == "merge-gate.yml"

    (tmp_path / "release-devkit.yaml").write_text("packages: {}\n", encoding="utf-8")
    assert default_workflows()[1].name == "release.yml"


def release_document(jobs: str, name: str = "Release", group: str = "release-${{ github.ref }}") -> str:
    return f"name: {name}\nconcurrency:\n  group: {group}\njobs:\n{jobs}"


def test_valid_release_workflow_has_no_problems(tmp_path: Path) -> None:
    jobs = job_block(
        "release",
        f"{RELEASE_CHECKOUT_WITH_TAGS_PUSH_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_STABLE_RUN}"
        f"{RELEASE_ENV}",
    )
    path = write_workflow(tmp_path, release_document(jobs), name="release.yml")
    assert validate_workflow_file(path) == []


def test_dev_channel_job_in_release_workflow_is_clean(tmp_path: Path) -> None:
    jobs = job_block(
        "prerelease",
        f"{RELEASE_CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_DEV_RUN}{RELEASE_ENV}",
    ) + job_block(
        "release",
        f"{RELEASE_CHECKOUT_WITH_TAGS_PUSH_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_STABLE_RUN}"
        f"{RELEASE_ENV}",
    )
    path = write_workflow(tmp_path, release_document(jobs), name="release.yml")
    assert validate_workflow_file(path) == []


def test_nuget_release_job_with_mint_step_is_clean(tmp_path: Path) -> None:
    jobs = job_block(
        "release",
        f"{RELEASE_CHECKOUT_WITH_TAGS_PUSH_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{NUGET_LOGIN_STEP}"
        f"{RELEASE_STABLE_RUN}{RELEASE_NUGET_ENV}",
    )
    path = write_workflow(tmp_path, release_document(jobs), name="release.yml")
    assert validate_workflow_file(path, nuget=True) == []


def test_release_workflow_name_is_pinned(tmp_path: Path) -> None:
    jobs = job_block(
        "release",
        f"{RELEASE_CHECKOUT_WITH_TAGS_PUSH_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_STABLE_RUN}"
        f"{RELEASE_ENV}",
    )
    path = write_workflow(tmp_path, release_document(jobs, name="Publish"), name="release.yml")
    problems = validate_workflow_file(path)
    assert any("workflow name must be Release" in problem for problem in problems)


def test_release_workflow_concurrency_is_pinned(tmp_path: Path) -> None:
    jobs = job_block(
        "release",
        f"{RELEASE_CHECKOUT_WITH_TAGS_PUSH_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_STABLE_RUN}"
        f"{RELEASE_ENV}",
    )
    document = release_document(jobs, group="publish-${{ github.ref }}")
    path = write_workflow(tmp_path, document, name="release.yml")
    problems = validate_workflow_file(path)
    assert any("concurrency group must be release-" in problem for problem in problems)

    cancelling = release_document(jobs).replace(
        "  group: release-${{ github.ref }}\n", "  group: release-${{ github.ref }}\n  cancel-in-progress: true\n"
    )
    path = write_workflow(tmp_path, cancelling, name="release.yml")
    problems = validate_workflow_file(path)
    assert any("cancel-in-progress" in problem for problem in problems)


def test_stable_channel_must_live_in_the_release_job(tmp_path: Path) -> None:
    jobs = job_block(
        "deliver",
        f"{RELEASE_CHECKOUT_WITH_TAGS_PUSH_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_STABLE_RUN}"
        f"{RELEASE_ENV}",
    )
    path = write_workflow(tmp_path, release_document(jobs), name="release.yml")
    problems = validate_workflow_file(path)
    assert any("stable channel must run in the 'release' job" in problem for problem in problems)


def test_dev_channel_must_live_in_the_prerelease_job(tmp_path: Path) -> None:
    jobs = job_block(
        "deliver",
        f"{RELEASE_CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_DEV_RUN}{RELEASE_ENV}",
    )
    path = write_workflow(tmp_path, release_document(jobs), name="release.yml")
    problems = validate_workflow_file(path)
    assert any("dev channel must run in the 'prerelease' job" in problem for problem in problems)


def test_release_checkout_must_not_spell_a_ref(tmp_path: Path) -> None:
    with_ref = (
        "  release:\n    steps:\n      - uses: actions/checkout@v5\n        with:\n"
        "          ref: ${{ github.event.pull_request.head.sha }}\n"
        "          fetch-depth: 0\n          fetch-tags: true\n          persist-credentials: true\n"
        f"{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_STABLE_RUN}{RELEASE_ENV}"
    )
    path = write_workflow(tmp_path, release_document(with_ref), name="release.yml")
    problems = validate_workflow_file(path)
    assert any("matches no signature" in problem for problem in problems)


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
    steps = (
        f"{MERGE_BOT_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    )
    path = write_workflow(tmp_path, merge_gate_document(steps), name="merge-gate.yml")
    assert validate_workflow_file(path) == []


def test_merge_gate_requires_merge_bot_checkout(tmp_path: Path) -> None:
    steps = f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    path = write_workflow(tmp_path, merge_gate_document(steps), name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("no merge-bot checkout precedes" in problem for problem in problems)


def test_merge_bot_checkout_reserved_for_merge_gate_jobs(tmp_path: Path) -> None:
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_DEV_RUN}"
    jobs = f"jobs:\n  prerelease:\n    steps:\n{steps}"
    problems = validate_workflow_file(write_workflow(tmp_path, jobs))
    assert any("merge-bot checkout is reserved" in problem for problem in problems)


def test_merge_gate_requires_canonical_mint_step(tmp_path: Path) -> None:
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    path = write_workflow(tmp_path, merge_gate_document(steps), name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("requires a canonical actions/create-github-app-token@v3 mint step" in problem for problem in problems)


def test_merge_gate_rejects_non_canonical_mint_inputs(tmp_path: Path) -> None:
    renamed_app_step = MINT_STEP.replace("app-id: ${{ vars.MERGE_BOT_APP_ID }}", "app-id: 123456")
    steps = (
        f"{MERGE_BOT_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{renamed_app_step}{MERGE_GATE_RUN}"
        f"{MERGE_GATE_ENV}"
    )
    path = write_workflow(tmp_path, merge_gate_document(steps), name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("canonical mint step" in problem for problem in problems)


def test_merge_gate_requires_minted_token_env(tmp_path: Path) -> None:
    wrong_env = MERGE_GATE_ENV.replace("${{ steps.mint.outputs.token }}", "${{ github.token }}")
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{wrong_env}"
    path = write_workflow(tmp_path, merge_gate_document(steps), name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("merge-gate requires env GITHUB_TOKEN" in problem for problem in problems)


def test_merge_gate_requires_head_sha_flag(tmp_path: Path) -> None:
    step = (
        '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev'
        " merge-gate --repository ${{ github.repository }}\n"
    )
    steps = f"{MERGE_BOT_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{MINT_STEP}{step}{MERGE_GATE_ENV}"
    path = write_workflow(tmp_path, merge_gate_document(steps), name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("carries rejected arguments" in problem for problem in problems)


def test_merge_gate_workflow_requires_labeled_trigger_only(tmp_path: Path) -> None:
    steps = (
        f"{MERGE_BOT_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    )
    document = merge_gate_document(steps).replace("    types: [labeled]\n", "    types: [labeled, opened]\n")
    path = write_workflow(tmp_path, document, name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("must trigger on pull_request to dev" in problem for problem in problems)


def test_merge_gate_workflow_requires_dev_branch_scope(tmp_path: Path) -> None:
    steps = (
        f"{MERGE_BOT_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    )
    document = merge_gate_document(steps).replace("    branches: [dev]\n", "")
    path = write_workflow(tmp_path, document, name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("must trigger on pull_request to dev" in problem for problem in problems)


def test_merge_gate_workflow_requires_workflow_run_wake(tmp_path: Path) -> None:
    steps = (
        f"{MERGE_BOT_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    )
    document = merge_gate_document(steps).replace(
        "  workflow_run:\n    workflows: [Integrate]\n    types: [completed]\n", ""
    )
    path = write_workflow(tmp_path, document, name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("must trigger on workflow_run from Integrate" in problem for problem in problems)


def test_merge_gate_workflow_pins_the_integrate_workflow_name(tmp_path: Path) -> None:
    steps = (
        f"{MERGE_BOT_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    )
    document = merge_gate_document(steps).replace("workflows: [Integrate]", "workflows: [CI]")
    path = write_workflow(tmp_path, document, name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("must trigger on workflow_run from Integrate" in problem for problem in problems)


def test_merge_gate_workflow_requires_the_per_pr_concurrency_group(tmp_path: Path) -> None:
    steps = (
        f"{MERGE_BOT_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    )
    document = merge_gate_document(steps).replace(
        "group: merge-gate-${{ github.event.pull_request.number || github.event.workflow_run.head_branch }}",
        "group: merge-gate",
    )
    path = write_workflow(tmp_path, document, name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("concurrency group must be" in problem for problem in problems)


def test_merge_gate_workflow_refuses_cancel_in_progress(tmp_path: Path) -> None:
    steps = (
        f"{MERGE_BOT_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    )
    document = merge_gate_document(steps).replace("head_branch }}\n", "head_branch }}\n  cancel-in-progress: true\n")
    path = write_workflow(tmp_path, document, name="merge-gate.yml")
    problems = validate_workflow_file(path)
    assert any("cancel-in-progress" in problem for problem in problems)


def test_merge_gate_workflow_jobs_require_the_dual_wake_gate(tmp_path: Path) -> None:
    steps = (
        f"{MERGE_BOT_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}{MERGE_GATE_ENV}"
    )
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
    "    - shell: bash\n"
    "      env:\n"
    f"        {WRAPPER_COMMIT_ENV_VAR}: " + "a" * 40 + "\n"
    "      run: |\n"
    "        git clone https://github.com/outernet-foundation/release-devkit.git"
    ' "$RUNNER_TEMP/release-devkit"\n'
    f'        git -C "$RUNNER_TEMP/release-devkit" checkout "${WRAPPER_COMMIT_ENV_VAR}"\n'
)


def test_valid_wrapper_passes(tmp_path: Path) -> None:
    assert validate_devkit_wrapper(write_wrapper(tmp_path, VALID_WRAPPER_STEPS)) == []


def test_wrapper_rejects_short_sha(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEPS.replace("a" * 40, "4712f1e")
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any(WRAPPER_COMMIT_ENV_VAR in problem for problem in problems)


def test_wrapper_rejects_extra_steps(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEPS + "    - uses: astral-sh/setup-uv@v7\n"
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("exactly one step" in problem for problem in problems)


def test_wrapper_rejects_wrong_repository(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEPS.replace(
        "https://github.com/outernet-foundation/release-devkit.git",
        "https://github.com/someone-else/release-devkit.git",
    )
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("clone" in problem for problem in problems)


def test_wrapper_rejects_missing_env_pin(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEPS.replace(
        "    - shell: bash\n      env:\n" + f"        {WRAPPER_COMMIT_ENV_VAR}: " + "a" * 40 + "\n",
        "    - shell: bash\n",
    )
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any(WRAPPER_COMMIT_ENV_VAR in problem for problem in problems)


def test_wrapper_rejects_missing_shell(tmp_path: Path) -> None:
    steps = VALID_WRAPPER_STEPS.replace("    - shell: bash\n      env:\n", "    - env:\n")
    problems = validate_devkit_wrapper(write_wrapper(tmp_path, steps))
    assert any("shell: bash" in problem for problem in problems)
