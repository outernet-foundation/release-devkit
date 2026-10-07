from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer
from bashrun.bash import bash_output

from release_devkit.config import DEFAULT_CONFIG_PATH
from release_devkit.context import merge_push_context
from release_devkit.drafts import (
    ANCHOR_PATTERN,
    DEV_DRAFT_TAG,
    edit_release_notes,
    ensure_draft_release,
    latest_app_versions,
    stage_and_upload,
)
from release_devkit.plan import package_rows, package_version_overrides
from release_devkit.publishing import publish_packages
from release_devkit.rendering import collect_app_rows, render_release_body

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)

_MERGE_PR_PATTERN = re.compile(r"Merge PR #(\d+): (.+)")


@app.command()
def main(
    config: Annotated[Path, typer.Option(help="Publish configuration YAML")] = DEFAULT_CONFIG_PATH,
) -> None:
    context = merge_push_context(config)

    _, published = publish_packages(context, dev=True)

    packages = context.publish_config.packages

    pr_number, pr_title = _MERGE_PR_PATTERN.findall(bash_output(f"git log -1 --format=%B {context.head}").strip())[0]

    app_last_versions = latest_app_versions(context)

    body = ensure_draft_release(context, DEV_DRAFT_TAG)

    staged = stage_and_upload(context, DEV_DRAFT_TAG, context.short)

    anchor = f"sha-{context.short}"
    parts = ANCHOR_PATTERN.split(body)
    sections: list[tuple[str, str]] = [
        (parts[index], parts[index + 1].strip() if index + 1 < len(parts) else "") for index in range(1, len(parts), 2)
    ]

    app_rows = collect_app_rows(staged, app_last_versions, context.settings.github_repository, DEV_DRAFT_TAG)

    body = render_release_body(
        f"### [{context.short}]({context.commit_url})"
        f" — [PR #{pr_number}: {pr_title}](https://github.com/{context.settings.github_repository}/pull/{pr_number})",
        package_rows(packages, package_version_overrides(packages, published)),
        app_rows,
        context.manifest,
        level=4,
    )

    new_entry = (anchor, body)
    for index, (existing_anchor, _) in enumerate(sections):
        if existing_anchor == anchor:
            sections[index] = new_entry
            break
    else:
        sections.insert(0, new_entry)

    edit_release_notes(
        context,
        DEV_DRAFT_TAG,
        "\n\n".join([f'<a id="{anchor_id}"></a>\n{content}' for anchor_id, content in sections]),
        publish=False,
    )
