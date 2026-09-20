import hashlib
from datetime import datetime
from pathlib import PurePosixPath

import httpx

from app.services.harness import ADDITIONAL_TESTS_SKIPPED


class ReproductionTestPathError(ValueError):
    """Persisted reproduction test path is not a safe repository-relative path."""


def validate_reproduction_test_path(raw: str | None) -> str:
    text = (raw or "").replace("\\", "/").strip()
    if not text:
        raise ReproductionTestPathError(
            "cannot create PR: invalid reproduction test path"
        )
    lowered = text.lower()
    if lowered.startswith("file:"):
        raise ReproductionTestPathError(
            "cannot create PR: invalid reproduction test path"
        )
    if text.startswith("/") or text.startswith("~"):
        raise ReproductionTestPathError(
            "cannot create PR: invalid reproduction test path"
        )
    first = text.split("/", 1)[0]
    if len(first) >= 2 and first[1] == ":":
        raise ReproductionTestPathError(
            "cannot create PR: invalid reproduction test path"
        )
    parts: list[str] = []
    for part in PurePosixPath(text).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise ReproductionTestPathError(
                "cannot create PR: invalid reproduction test path"
            )
        parts.append(part)
    if not parts:
        raise ReproductionTestPathError(
            "cannot create PR: invalid reproduction test path"
        )
    return "/".join(parts)


def _reported(value) -> str:
    if value is None:
        return "not recorded"
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    return text if text else "not recorded"


def additional_suite_label(patch_status: str | None, patch_stdout: str | None) -> str:
    if (patch_status or "") != "applied":
        return "not recorded"
    if patch_stdout == ADDITIONAL_TESTS_SKIPPED:
        return "skipped"
    return "ran"


def patch_sha256(diff: str | None) -> str:
    return hashlib.sha256((diff or "").encode("utf-8")).hexdigest()


def build_pr_body(
    *,
    run_id: int,
    repo: str | None,
    ref: str | None,
    source_sha: str | None,
    diagnostic_path: str | None,
    test_path: str | None,
    reproduced: bool | None,
    reproduction_exit_code: int | None,
    patch_attempt_id: int | None,
    patch_status: str | None,
    patch_stdout: str | None,
    current_diff: str | None,
    merge_approved_at: datetime | None,
    approval_device_id: str | None,
) -> str:
    if reproduced is True:
        reproduction_result = "reproduced"
    elif reproduced is False:
        reproduction_result = "not reproduced"
    else:
        reproduction_result = "not recorded"
    included = _reported(test_path)
    return (
        "## AutoPatch Verification Report\n"
        "\n"
        f"- Run ID: {_reported(run_id)}\n"
        f"- Repository: {_reported(repo)}\n"
        f"- Ref: {_reported(ref)}\n"
        f"- Source SHA: {_reported(source_sha)}\n"
        f"- Diagnostic path: {_reported(diagnostic_path)}\n"
        f"- Reproduction test: {included}\n"
        f"- Reproduction result: {reproduction_result}\n"
        f"- Reproduction exit code: {_reported(reproduction_exit_code)}\n"
        f"- Patch attempt: {_reported(patch_attempt_id)}\n"
        f"- Patch status: {_reported(patch_status)}\n"
        "- Additional suite: "
        f"{additional_suite_label(patch_status, patch_stdout)}\n"
        f"- Merge approval: {_reported(merge_approved_at)}\n"
        f"- Approval device: {_reported(approval_device_id)}\n"
        f"- Patch SHA-256: {patch_sha256(current_diff)}\n"
        "\n"
        "### Reproduction Test\n"
        "The synthesized reproduction/regression test used during verification "
        f"is included in this PR at `{included}`.\n"
        "\n"
        "### Verification Notes\n"
        "Only facts persisted by AutoPatch are reported. Command transcripts, "
        "parsed test counts, post-patch exit codes, and timings are not stored.\n"
    )


def create_pull_request(
    token: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str,
) -> dict:
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"https://api.github.com/repos/{repo}/pulls",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            },
        )
    response.raise_for_status()
    return response.json()
