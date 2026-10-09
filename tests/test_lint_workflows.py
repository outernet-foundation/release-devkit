import re
import tomllib
from pathlib import Path

import pytest
import typer

from release_devkit.verbs import get_app_version, lint_workflows, merge_gate, release, validate_release_plan
from release_devkit.verbs.lint_workflows import (
    DRY_RUN_SUFFIX,
    RELEASE_CHANNELS,
    UNENFORCED_FLAGS,
    VERB_SPECS,
    VerbStep,
    found_workflows,
    spec_env,
    validate_devkit_wrapper,
    validate_workflow_file,
)


def write_workflow(tmp_path: Path, text: str, name: str = "workflow.yml") -> Path:
    workflow_path = tmp_path / name
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(text, encoding="utf-8")
    return workflow_path


CHECKOUT_BLOCK = """
      - uses: ./.github/actions/checkout
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          persist-credentials: false
"""

CHECKOUT_WITH_TAGS_BLOCK = """
      - uses: ./.github/actions/checkout
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
          fetch-tags: true
          persist-credentials: false
"""

RELEASE_CHECKOUT_WITH_TAGS_BLOCK = """
      - uses: ./.github/actions/checkout
        with:
          fetch-depth: 0
          fetch-tags: true
          persist-credentials: false
"""

RELEASE_CHECKOUT_WITH_TAGS_PUSH_BLOCK = """
      - uses: ./.github/actions/checkout
        with:
          fetch-depth: 0
          fetch-tags: true
          persist-credentials: true
"""

RELEASE_CHECKOUT_WITH_REF_BLOCK = """
      - uses: ./.github/actions/checkout
        with:
          ref: main
          fetch-depth: 0
          fetch-tags: true
          persist-credentials: false
"""

MERGE_GATE_CHECKOUT_BLOCK = """
      - uses: ./.github/actions/checkout
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
          persist-credentials: false
"""

SETUP_UV_RESTORE_STEP = """
      - uses: ./.github/actions/setup-uv
        with:
          enable-cache: true
          save-cache: "false"
"""

SAVER_SETUP_UV_STEP = """
      - uses: ./.github/actions/setup-uv
        with:
          enable-cache: true
          save-cache: "true"
"""

WRAPPER_STEP = """
      - uses: ./.github/actions/setup-release-devkit
"""

MINT_STEP = (
    "      - uses: ./.github/actions/mint-token\n"
    "        id: mint\n"
    "        with:\n"
    "          app-id: ${{ vars.MERGE_BOT_APP_ID }}\n"
    "          private-key: ${{ secrets.MERGE_BOT_APP_PRIVATE_KEY }}\n"
)

NUGET_LOGIN_STEP = (
    "      - uses: ./.github/actions/nuget-login\n"
    "        id: nuget-login\n"
    "        with:\n"
    "          user: ${{ secrets.NUGET_USER }}\n"
)

DEVKIT_CLONE_STEP = (
    "      - name: Self-test install (this PR's head, consumer geometry, into RUNNER_TEMP)\n"
    "        run: >\n"
    '          git clone https://github.com/outernet-foundation/release-devkit.git "$RUNNER_TEMP/release-devkit"\n'
    '          && git -C "$RUNNER_TEMP/release-devkit" checkout ${{ github.event.pull_request.head.sha }}\n'
)

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

MERGE_GATE_RUN = (
    '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev'
    " merge-gate --head-sha ${{ github.event.pull_request.head.sha }}\n"
)

MERGE_GATE_DRY_RUN_RUN = (
    "      - run: >\n"
    '          uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev'
    " merge-gate --head-sha ${{ github.event.pull_request.head.sha }} --dry-run\n"
)

MERGE_GATE_ENV = "        env:\n          GITHUB_TOKEN: ${{ steps.mint.outputs.token }}\n"

MERGE_GATE_DRY_RUN_ENV = "        env:\n          GITHUB_TOKEN: ${{ github.token }}\n"

RELEASE_NUGET_ENV = (
    "        env:\n"
    "          GITHUB_TOKEN: ${{ github.token }}\n"
    "          NUGET_API_KEY: ${{ steps.nuget-login.outputs.NUGET_API_KEY }}\n"
)


def workflow(*job_blocks: str) -> str:
    return "jobs:\n" + "".join(job_blocks)


def job_block(job_name: str, steps: str, needs: list[str] | None = None, if_condition: str | None = None) -> str:
    needs_block = f"    needs: [{', '.join(needs)}]\n" if needs is not None else ""
    if_block = f"    if: {if_condition}\n" if if_condition is not None else ""
    return f"  {job_name}:\n{needs_block}{if_block}    steps:{steps}"


def valid_integrate() -> str:
    return (
        "name: Integrate\n"
        "on:\n"
        "  workflow_dispatch:\n"
        "  pull_request:\n"
        "    branches: [dev]\n"
        "jobs:\n"
        f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}"
        f"  preflight:\n    needs: [lint-workflows]\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
        "      - run: uv run preflight-python\n"
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}"
        f"{VALIDATE_RELEASE_PLAN_RUN}"
        f"  update-pr-draft-release:\n    if: github.event.pull_request\n"
        f"    needs: [validate-release-plan]\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}"
        f"{WRAPPER_STEP}{RELEASE_PR_RUN}{RELEASE_ENV}"
    )


def valid_release() -> str:
    return (
        "name: Release\n"
        "on:\n"
        "  push:\n"
        "    branches: [main, dev]\n"
        "concurrency:\n"
        "  group: release-${{ github.ref }}\n"
        "jobs:\n"
        f"  prerelease:\n    steps:{RELEASE_CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}"
        f"{RELEASE_DEV_RUN}{RELEASE_ENV}"
        f"  release:\n    steps:{RELEASE_CHECKOUT_WITH_TAGS_PUSH_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}"
        f"{RELEASE_STABLE_RUN}{RELEASE_ENV}"
    )


def valid_merge_gate() -> str:
    return (
        "name: Merge gate\n"
        "on:\n"
        "  pull_request:\n"
        "    branches: [dev]\n"
        "    types: [labeled]\n"
        "concurrency:\n"
        "  group: merge-gate-${{ github.event.pull_request.number }}\n"
        "jobs:\n"
        "  merge-gate:\n"
        "    if: github.event.label.name == 'ready-to-merge'\n"
        f"    steps:{MERGE_GATE_CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{MINT_STEP}{MERGE_GATE_RUN}"
        f"{MERGE_GATE_ENV}"
    )


VALID_WRAPPER = (
    "name: setup-release-devkit\n"
    "description: Install release-devkit at the pinned commit into RUNNER_TEMP\n"
    "runs:\n"
    "  using: composite\n"
    "  steps:\n"
    "    - shell: bash\n"
    "      env:\n"
    "        RELEASE_DEVKIT_COMMIT: ad4215260f7b24ec36d94ddc2ba6660be8afc5fb\n"
    "      run: |\n"
    '        git clone https://github.com/outernet-foundation/release-devkit.git "$RUNNER_TEMP/release-devkit"\n'
    '        git -C "$RUNNER_TEMP/release-devkit" checkout "$RELEASE_DEVKIT_COMMIT"\n'
)


def write_wrapper(tmp_path: Path, text: str = VALID_WRAPPER) -> None:
    wrapper = tmp_path / ".github/actions/setup-release-devkit/action.yml"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(text, encoding="utf-8")


def cli_option_flags(app: typer.Typer) -> set[str]:
    command = typer.main.get_command(app)
    return {param.opts[0] for param in command.params if param.opts}


def flags_in(pattern: str) -> set[str]:
    return set(re.findall(r"--[a-z][a-z-]*", pattern))


def test_verb_spec_table_matches_the_console_scripts() -> None:
    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    scripts: dict[str, str] = pyproject["project"]["scripts"]
    assert sorted([*VERB_SPECS, "release"]) == sorted(scripts)


def test_every_cli_flag_is_enforced_or_consciously_unenforced() -> None:
    apps = {
        "get-app-version": get_app_version.app,
        "lint-workflows": lint_workflows.app,
        "merge-gate": merge_gate.app,
        "release": release.app,
        "validate-release-plan": validate_release_plan.app,
    }
    for verb, app in apps.items():
        spec = VERB_SPECS.get(verb)
        enforced: set[str] = flags_in(spec.args.pattern) if spec is not None else set()
        if spec is not None and spec.dry_run_env is not None:
            enforced = enforced | {"--dry-run"}
        if verb == "release":
            enforced = enforced | {
                flag for channel in RELEASE_CHANNELS.values() for flag in flags_in(channel.args.pattern)
            }
        expected: set[str] = enforced | set(UNENFORCED_FLAGS.get(verb, frozenset()))
        assert cli_option_flags(app) == expected, f"{verb}: CLI flags do not match the lint grammar"


def test_release_channel_choices_match_the_spec_table() -> None:
    command = typer.main.get_command(release.app)
    channel_option = next(param for param in command.params if param.opts and param.opts[0] == "--channel")
    choices = getattr(channel_option.type, "choices", None)
    assert choices is not None
    assert set(choices) == set(RELEASE_CHANNELS)


def test_dry_run_invocation_takes_the_github_token_env() -> None:
    spec = VERB_SPECS["merge-gate"]
    landing = VerbStep(step_index=0, name="merge-gate", args=" --head-sha x", channel=None, spec=spec)
    dry = VerbStep(step_index=0, name="merge-gate", args=f" --head-sha x{DRY_RUN_SUFFIX}", channel=None, spec=spec)
    assert spec_env(landing) == {"GITHUB_TOKEN": "${{ steps.mint.outputs.token }}"}
    assert spec_env(dry) == {"GITHUB_TOKEN": "${{ github.token }}"}


def test_found_scan_discovers_yml_and_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_workflow(tmp_path, workflow("  a:\n    steps: []\n"), name=".github/workflows/b.yaml")
    write_workflow(tmp_path, workflow("  a:\n    steps: []\n"), name=".github/workflows/a.yml")
    assert found_workflows() == [
        Path(".github/workflows/a.yml"),
        Path(".github/workflows/b.yaml"),
    ]


def test_no_found_workflows_is_not_a_problem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".github/workflows").mkdir(parents=True)
    monkeypatch.setattr(lint_workflows, "run_actionlint", lambda: None)
    monkeypatch.setattr(lint_workflows, "run_zizmor", lambda: None)
    assert lint_workflows.main() is None


def test_valid_canonical_files_have_no_problems(tmp_path: Path) -> None:
    write_wrapper(tmp_path)
    assert validate_workflow_file(write_workflow(tmp_path, valid_integrate(), "integrate.yml")) == []
    assert validate_workflow_file(write_workflow(tmp_path, valid_release(), "release.yml")) == []
    assert validate_workflow_file(write_workflow(tmp_path, valid_merge_gate(), "merge-gate.yml")) == []


def test_non_canonical_filename_gets_signature_checks_only(tmp_path: Path) -> None:
    jobs = (
        f"  preflight:\n    needs: [some-root]\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}"
        "      - run: uv run repo-own-verb --flag\n"
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "cesium.yml")) == []


def test_bad_verb_spelling_flags_in_non_canonical_files(tmp_path: Path) -> None:
    step = '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev lint-workflows --extra\n'
    jobs = job_block("legs", f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "cesium.yml"))
    assert any("carries rejected arguments" in problem for problem in problems)


def test_path_mentions_alone_are_unflagged(tmp_path: Path) -> None:
    jobs = (
        f"  preflight:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SAVER_SETUP_UV_STEP}{DEVKIT_CLONE_STEP}"
        f"{VALIDATE_RELEASE_PLAN_RUN}"
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "integrate.yml")) == []


def test_directory_invocation_is_an_unflagged_path_mention(tmp_path: Path) -> None:
    step = '      - run: uv run --directory "$RUNNER_TEMP/release-devkit" --locked --no-dev lint-workflows\n'
    jobs = job_block("lint-workflows", f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}")
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "integrate.yml")) == []


def test_verb_step_must_consist_solely_of_canonical_invocations(tmp_path: Path) -> None:
    step = (
        '      - run: echo preamble && uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev'
        " lint-workflows\n"
    )
    jobs = job_block("lint-workflows", f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "integrate.yml"))
    assert any("solely of canonical" in problem for problem in problems)


def test_two_canonical_invocations_in_one_step_pass(tmp_path: Path) -> None:
    step = (
        '      - run: uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev validate-release-plan'
        ' && uv run --project "$RUNNER_TEMP/release-devkit" --locked --no-dev lint-workflows\n'
    )
    jobs = job_block("validate-release-plan", f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{step}")
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "integrate.yml")) == []


def test_checkout_must_use_the_repo_wrapper(tmp_path: Path) -> None:
    direct = CHECKOUT_BLOCK.replace("./.github/actions/checkout", "actions/checkout@v5")
    jobs = job_block("lint-workflows", f"{direct}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "integrate.yml"))
    assert any("checkout must be ./.github/actions/checkout" in problem for problem in problems)


def test_persist_credentials_false_is_required(tmp_path: Path) -> None:
    implicit = """
      - uses: ./.github/actions/checkout
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          fetch-depth: 0
          fetch-tags: true
"""
    jobs = job_block(
        "validate-release-plan", f"{implicit}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{VALIDATE_RELEASE_PLAN_RUN}"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "integrate.yml"))
    assert any("persist-credentials: false" in problem for problem in problems)


def test_persist_true_is_reserved_for_the_stable_push_form(tmp_path: Path) -> None:
    dev_jobs = job_block(
        "prerelease", f"{RELEASE_CHECKOUT_WITH_TAGS_PUSH_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_DEV_RUN}"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(dev_jobs), "release.yml"))
    assert any("persist-credentials: false" in problem for problem in problems)

    untagged_push = RELEASE_CHECKOUT_WITH_TAGS_PUSH_BLOCK.replace("          fetch-tags: true\n", "")
    stable_jobs = job_block(
        "release", f"{untagged_push}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_STABLE_RUN}{RELEASE_ENV}"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(stable_jobs), "release.yml"))
    assert any("persist-credentials: false" in problem for problem in problems)


def test_integrate_ref_law_demands_the_pr_head_ref(tmp_path: Path) -> None:
    wrong_ref = CHECKOUT_BLOCK.replace(
        "${{ github.event.pull_request.head.sha }}", "${{ github.event.workflow_run.head_sha }}"
    )
    jobs = job_block("lint-workflows", f"{wrong_ref}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}")
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "integrate.yml"))
    assert any("checkout ref must be" in problem for problem in problems)


def test_release_ref_law_forbids_any_ref(tmp_path: Path) -> None:
    jobs = job_block(
        "prerelease",
        f"{RELEASE_CHECKOUT_WITH_REF_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_DEV_RUN}{RELEASE_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "release.yml"))
    assert any("must carry no ref" in problem for problem in problems)


def test_no_ref_law_outside_canonical_files(tmp_path: Path) -> None:
    loose = """
      - uses: ./.github/actions/checkout
        with:
          ref: ${{ github.event.inputs.some-ref }}
          persist-credentials: false
"""
    jobs = job_block("build", f"{loose}{SETUP_UV_RESTORE_STEP}      - run: make native-package\n")
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "cesium.yml")) == []


def test_tag_consuming_verbs_need_the_tag_fetch_checkout(tmp_path: Path) -> None:
    jobs = job_block(
        "validate-release-plan", f"{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{VALIDATE_RELEASE_PLAN_RUN}"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "integrate.yml"))
    assert any("fetch-depth: 0 and fetch-tags: true" in problem for problem in problems)


def test_merge_gate_verb_needs_the_full_history_checkout(tmp_path: Path) -> None:
    shallow = MERGE_GATE_CHECKOUT_BLOCK.replace("          fetch-depth: 0\n", "")
    text = valid_merge_gate().replace(MERGE_GATE_CHECKOUT_BLOCK, shallow)
    problems = validate_workflow_file(write_workflow(tmp_path, text, "merge-gate.yml"))
    assert any("fetch-depth: 0" in problem for problem in problems)


def test_verb_job_requires_wrapper_or_clone_installation(tmp_path: Path) -> None:
    jobs = job_block(
        "validate-release-plan", f"{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{VALIDATE_RELEASE_PLAN_RUN}"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "integrate.yml"))
    assert any("must install release-devkit" in problem for problem in problems)


def test_clone_step_satisfies_installation(tmp_path: Path) -> None:
    jobs = (
        f"  preflight:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SAVER_SETUP_UV_STEP}{DEVKIT_CLONE_STEP}"
        f"{VALIDATE_RELEASE_PLAN_RUN}{MERGE_GATE_DRY_RUN_RUN}{MERGE_GATE_DRY_RUN_ENV}"
    )
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "integrate.yml")) == []


def test_merge_gate_env_reference_must_resolve_to_a_real_step(tmp_path: Path) -> None:
    without_mint = valid_merge_gate().replace(MINT_STEP, "")
    problems = validate_workflow_file(write_workflow(tmp_path, without_mint, "merge-gate.yml"))
    assert any("no step with that id" in problem for problem in problems)


def test_nuget_delivery_env_requires_the_minted_api_key(tmp_path: Path) -> None:
    without_login = valid_release().replace(
        f"{WRAPPER_STEP}{RELEASE_DEV_RUN}{RELEASE_ENV}",
        f"{WRAPPER_STEP}{RELEASE_DEV_RUN}{RELEASE_NUGET_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, without_login, "release.yml"), nuget=True)
    assert any("no step with that id" in problem for problem in problems)

    with_login = (
        valid_release()
        .replace(
            f"{WRAPPER_STEP}{RELEASE_DEV_RUN}{RELEASE_ENV}",
            f"{WRAPPER_STEP}{NUGET_LOGIN_STEP}{RELEASE_DEV_RUN}{RELEASE_NUGET_ENV}",
        )
        .replace(
            f"{WRAPPER_STEP}{RELEASE_STABLE_RUN}{RELEASE_ENV}",
            f"{WRAPPER_STEP}{NUGET_LOGIN_STEP}{RELEASE_STABLE_RUN}{RELEASE_NUGET_ENV}",
        )
    )
    assert validate_workflow_file(write_workflow(tmp_path, with_login, "release.yml"), nuget=True) == []


def test_non_nuget_repo_rejects_the_api_key_env(tmp_path: Path) -> None:
    jobs = job_block(
        "prerelease",
        f"{RELEASE_CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{NUGET_LOGIN_STEP}{RELEASE_DEV_RUN}"
        f"{RELEASE_NUGET_ENV}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "release.yml"), nuget=False)
    assert any("must not carry NUGET_API_KEY env" in problem for problem in problems)


def test_delivery_verbs_require_the_canonical_token_env(tmp_path: Path) -> None:
    jobs = job_block(
        "release", f"{RELEASE_CHECKOUT_WITH_TAGS_PUSH_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_STABLE_RUN}"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "release.yml"))
    assert any("release --channel stable requires env GITHUB_TOKEN" in problem for problem in problems)


def test_root_jobs_must_carry_no_needs(tmp_path: Path) -> None:
    text = valid_integrate().replace(
        "  lint-workflows:\n    steps:", "  lint-workflows:\n    needs: [update-pr-draft-release]\n    steps:"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, text, "integrate.yml"))
    assert any("parallel root" in problem for problem in problems)


def test_preflight_needs_exactly_the_present_roots(tmp_path: Path) -> None:
    missing_root = valid_integrate().replace("    needs: [lint-workflows]\n", "    needs: []\n")
    problems = validate_workflow_file(write_workflow(tmp_path, missing_root, "integrate.yml"))
    assert any("must need ['lint-workflows']" in problem for problem in problems)

    no_lint_job = (
        valid_integrate()
        .replace(
            f"  lint-workflows:\n    steps:{CHECKOUT_BLOCK}{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{LINT_WORKFLOWS_RUN}",
            "",
        )
        .replace("    needs: [lint-workflows]\n", "    needs: []\n")
    )
    assert validate_workflow_file(write_workflow(tmp_path, no_lint_job, "integrate.yml")) == []


def test_update_pr_draft_release_found_form(tmp_path: Path) -> None:
    ungated = valid_integrate().replace("    if: github.event.pull_request\n", "")
    problems = validate_workflow_file(write_workflow(tmp_path, ungated, "integrate.yml"))
    assert any("must gate on if: github.event.pull_request" in problem for problem in problems)

    orphan = valid_integrate().replace("    needs: [validate-release-plan]\n", "    needs: []\n")
    problems = validate_workflow_file(write_workflow(tmp_path, orphan, "integrate.yml"))
    assert any("must need validate-release-plan" in problem for problem in problems)


def test_pr_channel_must_run_in_its_named_job(tmp_path: Path) -> None:
    text = valid_integrate().replace("  update-pr-draft-release:", "  wrong-name:")
    problems = validate_workflow_file(write_workflow(tmp_path, text, "integrate.yml"))
    assert any("must run in the 'update-pr-draft-release' job" in problem for problem in problems)


def test_release_triggers_must_be_push_to_main_and_dev(tmp_path: Path) -> None:
    text = valid_release().replace("    branches: [main, dev]\n", "    branches: [main]\n")
    problems = validate_workflow_file(write_workflow(tmp_path, text, "release.yml"))
    assert any("must trigger on push" in problem for problem in problems)


def test_release_concurrency_is_the_delivery_queue(tmp_path: Path) -> None:
    cancelled = valid_release().replace(
        "  group: release-${{ github.ref }}\n", "  group: release-${{ github.ref }}\n  cancel-in-progress: true\n"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, cancelled, "release.yml"))
    assert any("omit cancel-in-progress" in problem for problem in problems)

    wrong_group = valid_release().replace("release-${{ github.ref }}", "other-${{ github.ref }}")
    problems = validate_workflow_file(write_workflow(tmp_path, wrong_group, "release.yml"))
    assert any("concurrency group must be" in problem for problem in problems)


def test_release_workflow_name_is_free(tmp_path: Path) -> None:
    renamed = valid_release().replace("name: Release\n", "name: Publish\n")
    assert validate_workflow_file(write_workflow(tmp_path, renamed, "release.yml")) == []


def test_dev_and_stable_channels_must_run_in_their_named_jobs(tmp_path: Path) -> None:
    swapped = valid_release().replace("  prerelease:\n", "  wrong-dev:\n").replace("  release:\n", "  wrong-stable:\n")
    problems = validate_workflow_file(write_workflow(tmp_path, swapped, "release.yml"))
    assert any("must run in the 'prerelease' job" in problem for problem in problems)
    assert any("must run in the 'release' job" in problem for problem in problems)


def test_merge_gate_trigger_and_gate_forms(tmp_path: Path) -> None:
    wrong_types = valid_merge_gate().replace("    types: [labeled]\n", "    types: [opened]\n")
    problems = validate_workflow_file(write_workflow(tmp_path, wrong_types, "merge-gate.yml"))
    assert any("must trigger on pull_request to dev" in problem for problem in problems)

    dual_wake = valid_merge_gate().replace(
        "    types: [labeled]\n", "    types: [labeled]\n  workflow_run:\n    workflows: [Integrate]\n"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, dual_wake, "merge-gate.yml"))
    assert any("workflow_run is forbidden" in problem for problem in problems)

    ungated = valid_merge_gate().replace("    if: github.event.label.name == 'ready-to-merge'\n", "    if: true\n")
    problems = validate_workflow_file(write_workflow(tmp_path, ungated, "merge-gate.yml"))
    assert any("must gate on if:" in problem for problem in problems)

    cancelling = valid_merge_gate().replace(
        "  group: merge-gate-${{ github.event.pull_request.number }}\n",
        "  group: merge-gate-x\n  cancel-in-progress: true\n",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, cancelling, "merge-gate.yml"))
    assert any("concurrency" in problem for problem in problems)


def test_merge_gate_ref_law_demands_the_single_payload_pr_head(tmp_path: Path) -> None:
    dual_payload = MERGE_GATE_CHECKOUT_BLOCK.replace(
        "${{ github.event.pull_request.head.sha }}",
        "${{ github.event.pull_request.head.sha || github.event.workflow_run.head_sha }}",
    )
    text = valid_merge_gate().replace(MERGE_GATE_CHECKOUT_BLOCK, dual_payload)
    problems = validate_workflow_file(write_workflow(tmp_path, text, "merge-gate.yml"))
    assert any("checkout ref must be" in problem for problem in problems)


def test_literal_block_run_steps_are_accepted(tmp_path: Path) -> None:
    block = (
        "      - name: Wipe workspace\n"
        "        run: |\n"
        '          find "$GITHUB_WORKSPACE" -mindepth 1 -delete\n'
        "          rm -rf ~/.cache/Unity\n"
    )
    jobs = f"  preflight:\n    steps:{CHECKOUT_BLOCK}{SAVER_SETUP_UV_STEP}{block}      - run: uv run preflight-python\n"
    assert validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "integrate.yml")) == []


def test_at_most_one_cache_writing_setup_uv_per_file(tmp_path: Path) -> None:
    double_saver = valid_integrate().replace(
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SETUP_UV_RESTORE_STEP}",
        f"  validate-release-plan:\n    steps:{CHECKOUT_WITH_TAGS_BLOCK}{SAVER_SETUP_UV_STEP}",
    )
    problems = validate_workflow_file(write_workflow(tmp_path, double_saver, "integrate.yml"))
    assert any("at most one cache-writing" in problem for problem in problems)


def test_environment_key_is_rejected(tmp_path: Path) -> None:
    jobs = (
        f"  prerelease:\n    environment: release\n    steps:{RELEASE_CHECKOUT_WITH_TAGS_BLOCK}"
        f"{SETUP_UV_RESTORE_STEP}{WRAPPER_STEP}{RELEASE_DEV_RUN}{RELEASE_ENV}"
    )
    problems = validate_workflow_file(write_workflow(tmp_path, workflow(jobs), "release.yml"))
    assert any("environment: key is forbidden" in problem for problem in problems)


def test_wrapper_absence_is_not_a_problem(tmp_path: Path) -> None:
    assert validate_devkit_wrapper(tmp_path / ".github/actions/setup-release-devkit/action.yml") == []


def test_wrapper_form_is_enforced_when_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_wrapper(tmp_path)
    assert validate_devkit_wrapper() == []

    short_pin = VALID_WRAPPER.replace("ad4215260f7b24ec36d94ddc2ba6660be8afc5fb", "ad42152")
    write_wrapper(tmp_path, short_pin)
    problems = validate_devkit_wrapper()
    assert any("pinned commit" in problem for problem in problems)
