from __future__ import annotations

import typer
from bashrun.bash import bash, bash_check, bash_output
from ci_devkit.ci_step import ci_step
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pydantic_settings import BaseSettings

from .draft_releases import delete_draft_release

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

BASE_BRANCH = "dev"
# The helper reads GITHUB_TOKEN from git's environment at credential time, so the token
# never appears in a logged command string or a process argument.
GIT_CREDENTIAL_HELPER = r"!f() { echo username=x-access-token; echo password=$GITHUB_TOKEN; }; f"
GIT_COMMAND = f"git -c credential.helper='{GIT_CREDENTIAL_HELPER}'"
GREEN_CONCLUSIONS = frozenset({"SUCCESS", "SKIPPED"})
GATE_CHECK_NAME = "merge-gate"
LABEL_NAME = "ready-to-merge"
WAITING_STATUSES = frozenset({"IN_PROGRESS", "QUEUED", "PENDING", "WAITING"})


class Settings(BaseSettings):
    head_sha: str
    github_repository: str = ""


class LabelEntry(BaseModel):
    name: str


class CheckEntry(BaseModel):
    name: str
    status: str | None = None
    conclusion: str | None = None


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
        battery = [entry for entry in pull_request.check_rollup if entry.name != GATE_CHECK_NAME]
        blocking = [
            entry for entry in battery if entry.status != "COMPLETED" or entry.conclusion not in GREEN_CONCLUSIONS
        ]
        if blocking:
            if all(entry.status in WAITING_STATUSES for entry in blocking):
                print(f"  checks still pending on PR #{pr_number} — the other wake will land it")
                return
            raise SystemExit(
                f"checks not green on PR #{pr_number} head {pull_request.head_oid[:12]} — see the PR's checks"
            )
        print(f"  {len(battery)} checks green on {pull_request.head_oid[:12]}")

    with ci_step("Merge to dev"):
        checked_out = bash_output("git rev-parse HEAD").strip()
        if checked_out != pull_request.head_oid:
            raise SystemExit(f"checkout HEAD {checked_out[:12]} is not the PR head {pull_request.head_oid[:12]}")
        bash(f"{GIT_COMMAND} fetch origin refs/heads/{BASE_BRANCH}")
        if not bash_check("git merge-base --is-ancestor FETCH_HEAD HEAD"):
            raise SystemExit(f"{BASE_BRANCH} has commits not on the PR head — rebase the PR onto {BASE_BRANCH}")
        bash("git checkout --detach FETCH_HEAD")
        bash(f'git merge --no-ff {pull_request.head_oid} -m "Merge PR #{pr_number}"')
        bash(f"{GIT_COMMAND} push origin HEAD:refs/heads/{BASE_BRANCH}")
        print(f"  {BASE_BRANCH} merged PR #{pr_number}")

    with ci_step("Delete merged branch"):
        head_ref = bash_output(f"gh pr view {pr_number} --json headRefName --jq .headRefName").strip()
        if head_ref and head_ref not in (BASE_BRANCH, "main"):
            if bash_check(f"{GIT_COMMAND} ls-remote --heads origin {head_ref}"):
                bash(f"{GIT_COMMAND} push origin --delete {head_ref}")
                print(f"  deleted branch {head_ref}")

    delete_draft_release(f"pr-{pr_number}", settings.github_repository)
