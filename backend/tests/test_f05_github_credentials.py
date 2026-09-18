from types import SimpleNamespace

import pytest

from app.db import SessionLocal
from app.models import ApprovalGate, SandboxRun
from app.services.e2b_runner import clone_and_read_sources, push_branch
from app.services.github_app import (
    PERMISSIONS_PR_WRITE,
    PERMISSIONS_REPO_READ,
    get_installation_token_sync,
    installation_token_for_repo,
)
from app.services.harness import ReproductionResult
from app.workers.tasks import apply_patch_and_verify, clone_and_index, open_github_pr
from tests.test_patch_pipeline import (
    SOURCE_FILES,
    _approve,
    _fake_sandbox,
    _seed_apply_verify_run,
    _seed_run,
    _stub_apply_verify,
    _stub_failed_follow_on_suite,
)


CLONE_URL = "https://github.com/acme/demo.git"
CLONE_TOKEN = "ghs_clone_secret_token"


class _Result:
    def __init__(self, stdout=""):
        self.stdout = stdout
        self.stderr = ""
        self.exit_code = 0


class RecordingSandbox:
    sandbox_id = "sbx-f05"

    def __init__(self, origin=CLONE_URL):
        self.ran = []
        self.origin = origin
        self.commands = SimpleNamespace(run=self._run)
        self.files = SimpleNamespace(read=lambda path: "")

    def _run(self, command, timeout=None, on_stdout=None, on_stderr=None):
        self.ran.append(command)
        if "config --get remote.origin.url" in command:
            return _Result(self.origin + "\n")
        if "git ls-files" in command:
            return _Result("")
        return _Result("")

    def kill(self):
        return None


def _httpx_capture(monkeypatch, token_value="ghs_scoped"):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"token": token_value}

    class Client:
        def __init__(self, timeout=30):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return Response()

    monkeypatch.setattr("app.services.github_app.httpx.Client", Client)
    monkeypatch.setattr("app.services.github_app.make_app_jwt", lambda: "app-jwt")
    return captured


def test_clone_origin_is_tokenless_https_url():
    sandbox = RecordingSandbox()
    files = clone_and_read_sources(sandbox, CLONE_URL, "main", CLONE_TOKEN)
    assert files == {}
    clone_cmd, set_url, origin_cmd, ls_cmd = sandbox.ran[:4]
    assert " clone " in clone_cmd
    assert "--depth 1" in clone_cmd
    assert "http.extraHeader=" in clone_cmd
    assert "Authorization: Bearer" in clone_cmd
    assert CLONE_TOKEN in clone_cmd
    assert "x-access-token" not in clone_cmd
    assert CLONE_URL in clone_cmd
    assert "remote set-url origin" in set_url
    assert CLONE_URL in set_url
    assert "x-access-token" not in set_url
    assert CLONE_TOKEN not in set_url
    assert "config --get remote.origin.url" in origin_cmd
    assert "git ls-files" in ls_cmd
    origin_index = sandbox.ran.index(origin_cmd)
    ls_index = sandbox.ran.index(ls_cmd)
    assert origin_index < ls_index


def test_clone_rejects_credential_left_in_origin():
    sandbox = RecordingSandbox(
        origin=(
            "https://x-access-token:ghs_clone_secret_token@github.com/acme/demo.git"
        )
    )
    with pytest.raises(RuntimeError, match="must not contain credentials"):
        clone_and_read_sources(sandbox, CLONE_URL, "main", CLONE_TOKEN)


def test_push_uses_command_local_header_not_origin_url():
    sandbox = RecordingSandbox()
    push_branch(sandbox, "autopatch/run-1", "ghs_write_secret")
    assert len(sandbox.ran) == 1
    command = sandbox.ran[0]
    assert "push origin" in command
    assert "http.extraHeader=" in command
    assert "x-access-token" not in command
    assert "remote set-url" not in command


def test_read_token_request_is_contents_read_and_repo_scoped(monkeypatch):
    captured = _httpx_capture(monkeypatch, "ghs_read")
    token = installation_token_for_repo(42, "acme/demo", PERMISSIONS_REPO_READ)
    assert token == "ghs_read"
    assert captured["json"]["permissions"] == {"contents": "read"}
    assert captured["json"]["repositories"] == ["demo"]
    assert "pull_requests" not in captured["json"]["permissions"]
    assert captured["url"].endswith("/app/installations/42/access_tokens")


def test_write_token_request_is_pr_write_and_repo_scoped(monkeypatch):
    captured = _httpx_capture(monkeypatch, "ghs_write")
    token = installation_token_for_repo(42, "acme/demo", PERMISSIONS_PR_WRITE)
    assert token == "ghs_write"
    assert captured["json"]["permissions"] == {
        "contents": "write",
        "pull_requests": "write",
    }
    assert captured["json"]["repositories"] == ["demo"]


def test_scoped_token_helper_fails_closed_without_permissions():
    with pytest.raises(ValueError, match="permissions are required"):
        get_installation_token_sync(1, permissions={}, repositories=["demo"])
    with pytest.raises(ValueError, match="permissions are required"):
        installation_token_for_repo(1, "acme/demo", {})


def test_scoped_token_helper_fails_closed_without_repository():
    with pytest.raises(ValueError, match="repository scope is required"):
        get_installation_token_sync(
            1, permissions=PERMISSIONS_REPO_READ, repositories=[]
        )
    with pytest.raises(ValueError, match="repository scope is required"):
        installation_token_for_repo(1, "demo", PERMISSIONS_REPO_READ)
    with pytest.raises(ValueError, match="repository scope is required"):
        installation_token_for_repo(1, "", PERMISSIONS_REPO_READ)


def test_clone_and_index_requests_read_token_only(monkeypatch):
    seen = []
    run_id, repo = _seed_run()
    _approve(run_id, "sandbox_provision")

    def capture(installation_id, owner_repo, permissions):
        seen.append(
            {
                "installation_id": installation_id,
                "owner_repo": owner_repo,
                "permissions": permissions,
            }
        )
        return "ghs_read"

    monkeypatch.setattr("app.workers.tasks.installation_token_for_repo", capture)
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: (_fake_sandbox(), SOURCE_FILES),
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        lambda sandbox: (0, "", ""),
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda *a, **k: ReproductionResult(
            exit_code=1,
            stdout="",
            stderr="ZeroDivisionError",
        ),
    )
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: "diff --git a/x b/x\n--- a/x\n+++ b/x\n",
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    clone_and_index.run(run_id)
    assert len(seen) == 1
    assert seen[0]["owner_repo"] == repo
    assert seen[0]["permissions"] == PERMISSIONS_REPO_READ


def test_apply_patch_requests_read_token_only(monkeypatch):
    seen = []
    run_id = _seed_apply_verify_run()
    _stub_apply_verify(monkeypatch)
    _stub_failed_follow_on_suite(monkeypatch)

    def capture(installation_id, owner_repo, permissions):
        seen.append(permissions)
        return "ghs_read"

    monkeypatch.setattr("app.workers.tasks.installation_token_for_repo", capture)
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: "diff --git a/y b/y\n--- a/y\n+++ b/y\n",
    )
    apply_patch_and_verify.run(run_id)
    assert seen == [PERMISSIONS_REPO_READ]


def test_open_github_pr_requests_write_token_after_merge_gate(monkeypatch):
    seen = []
    pushed = []
    run_id, repo = _seed_run(
        status="awaiting_merge",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        pipeline_stage="merge",
    )
    _approve(run_id, "merge")

    def capture(installation_id, owner_repo, permissions):
        seen.append(permissions)
        if permissions == PERMISSIONS_PR_WRITE:
            return "ghs_write"
        return "ghs_read"

    monkeypatch.setattr("app.workers.tasks.installation_token_for_repo", capture)
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: (_fake_sandbox(), SOURCE_FILES),
    )
    monkeypatch.setattr(
        "app.workers.tasks.apply_diff_in_sandbox",
        lambda sandbox, diff: (True, None),
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.run_sandbox_command",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.push_branch",
        lambda sandbox, branch, token: pushed.append(token),
    )
    monkeypatch.setattr(
        "app.workers.tasks.create_pull_request",
        lambda **kwargs: {"html_url": "https://github.com/acme/demo/pull/1"},
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    open_github_pr.run(run_id)
    assert seen == [PERMISSIONS_REPO_READ, PERMISSIONS_PR_WRITE]
    assert pushed == ["ghs_write"]
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "completed"
        gate = (
            db.query(ApprovalGate)
            .filter(ApprovalGate.run_id == run_id, ApprovalGate.gate == "merge")
            .one()
        )
        assert gate.status == "approved"
    finally:
        db.close()
