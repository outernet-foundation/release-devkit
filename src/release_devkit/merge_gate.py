from __future__ import annotations

import typer
from bashrun.bash import bash, bash_check, bash_output
from ci_devkit.ci_step import ci_step
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic_settings import BaseSettings

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

BASE_BRANCH = "dev"
# The helper reads GITHUB_TOKEN from git's environment at credential time, so the token
# never appears in a logged command string or a process argument.
GIT_CREDENTIAL_HELPER = r"!f() { echo username=x-access-token; echo password=$GITHUB_TOKEN; }; f"
GIT_COMMAND = f"git -c credential.helper='{GIT_CREDENTIAL_HELPER}'"
GREEN_CHECK_STATES = frozenset({"SUCCESS", "SKIPPED"})
LABEL_NAME = "ready-to-merge"
WAITING_CHECK_STATES = frozenset({"IN_PROGRESS", "QUEUED", "PENDING", "WAITING"})


class Settings(BaseSettings):
    head_sha: str


class LabelEntry(BaseModel):
    name: str


class CheckEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    state: str


class PullRequestRef(BaseModel):
    number: int
    head_oid: str = Field(alias="headRefOid")


class PullRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    state: str
    head_oid: str = Field(alias="headRefOid")
    labels: list[LabelEntry]
    check_rollup: list[CheckEntry] = Field(alias="statusCheckRollup")


PULL_REQUEST_REFS = TypeAdapter(list[PullRequestRef])


@app.command()
def main() -> None:
    settings = Settings.model_validate({})
    branches = bash_output(f"git branch -r --contains {settings.head_sha}").split()
    numbers: list[int] = []
    for branch in branches:
        name = branch.removeprefix("origin/")
        output = bash_output(f"gh pr list --head {name} --base {BASE_BRANCH} --json number,headRefOid")
        references = PULL_REQUEST_REFS.validate_json(output)
        numbers.extend(reference.number for reference in references if reference.head_oid == settings.head_sha)
    matches = sorted(set(numbers))
    if len(matches) != 1:
        rendered = ", ".join(str(number) for number in matches) or "none"
        raise SystemExit(f"head {settings.head_sha[:12]} matches {rendered} open PR(s) to {BASE_BRANCH}")
    pr_number = str(matches[0])
    pull_request = PullRequest.model_validate_json(
        bash_output(f"gh pr view {pr_number} --json state,headRefOid,labels,statusCheckRollup")
    )
    if pull_request.state != "OPEN":
        raise SystemExit(f"PR is {pull_request.state}, not OPEN — refusing to merge")
    if LABEL_NAME not in {label.name for label in pull_request.labels}:
        raise SystemExit(f"label {LABEL_NAME} absent — refusing to merge")

    with ci_step("Verify checks"):
        blocking = [entry for entry in pull_request.check_rollup if entry.state not in GREEN_CHECK_STATES]
        if blocking:
            if all(entry.state in WAITING_CHECK_STATES for entry in blocking):
                print(f"  checks still pending on PR #{pr_number} — the other wake will land it")
                return
            raise SystemExit(
                f"checks not green on PR #{pr_number} head {pull_request.head_oid[:12]} — see the PR's checks"
            )
        print(f"  {len(pull_request.check_rollup)} checks green on {pull_request.head_oid[:12]}")

    with ci_step("Fast-forward dev"):
        checked_out = bash_output("git rev-parse HEAD").strip()
        if checked_out != pull_request.head_oid:
            raise SystemExit(f"checkout HEAD {checked_out[:12]} is not the PR head {pull_request.head_oid[:12]}")
        bash(f"{GIT_COMMAND} fetch origin refs/heads/{BASE_BRANCH}")
        if not bash_check("git merge-base --is-ancestor FETCH_HEAD HEAD"):
            raise SystemExit(f"{BASE_BRANCH} has commits not on the PR head — rebase the PR onto {BASE_BRANCH}")
        bash(f"{GIT_COMMAND} push origin HEAD:refs/heads/{BASE_BRANCH}")
        print(f"  {BASE_BRANCH} fast-forwarded to {pull_request.head_oid[:12]}")
