from types import SimpleNamespace

from app.db import SessionLocal
from app.models import SandboxRun
from app.services.e2b_runner import clone_and_read_sources, parse_git_sha
from app.workers.tasks import apply_patch_and_verify, clone_and_index, open_github_pr
from tests.test_f05_github_credentials import CLONE_TOKEN, CLONE_URL, RecordingSandbox
from tests.test_patch_pipeline import (
    SOURCE_FILES,
    TEST_SOURCE_SHA,
    _approve,
    _fake_sandbox,
    _seed_apply_verify_run,
    _seed_run,
    _stub_apply_verify,
    _stub_failed_follow_on_suite,
)


OTHER_SHA = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
MOVED_REF = "moved-main"


def test_parse_git_sha_rejects_branch_and_zero():
    try:
        parse_git_sha("main")
    except ValueError:
        pass
    else:
        raise AssertionError("expected invalid git sha")
    try:
        parse_git_sha("0" * 40)
    except ValueError:
        pass
    else:
        raise AssertionError("expected zero sha rejected")
    assert parse_git_sha(TEST_SOURCE_SHA.upper()) == TEST_SOURCE_SHA


def test_clone_by_sha_fetches_and_checks_head():
    sandbox = RecordingSandbox(head_sha=TEST_SOURCE_SHA)
    clone_and_read_sources(
        sandbox, CLONE_URL, "main", CLONE_TOKEN, sha=TEST_SOURCE_SHA
    )
    joined = "\n".join(sandbox.ran)
    assert f"fetch --depth 1 origin {TEST_SOURCE_SHA}" in joined
    assert f"checkout --detach {TEST_SOURCE_SHA}" in joined
    assert "--branch main" not in joined
    assert "rev-parse HEAD" in joined
    assert "http.extraHeader=" in joined
    assert CLONE_TOKEN in joined
    assert "x-access-token" not in joined


def test_clone_by_sha_fails_closed_on_head_mismatch():
    sandbox = RecordingSandbox(head_sha=OTHER_SHA)
    try:
        clone_and_read_sources(
            sandbox, CLONE_URL, "main", CLONE_TOKEN, sha=TEST_SOURCE_SHA
        )
    except RuntimeError as exc:
        assert "does not match source_sha" in str(exc)
        return
    raise AssertionError("expected clone to fail closed")


def test_clone_and_index_persists_checkout_head_sha(monkeypatch):
    run_id, _repo = _seed_run()
    _approve(run_id, "sandbox_provision")
    captured = []

    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: captured.append(kwargs) or (_fake_sandbox(), SOURCE_FILES),
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        lambda sandbox: (0, "", ""),
    )
    monkeypatch.setattr(
        "app.workers.tasks.installation_token_for_repo",
        lambda *a, **k: "ghs_read",
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda *a, **k: SimpleNamespace(
            reproduced=True,
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
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.source_sha == TEST_SOURCE_SHA
        assert captured[0]["ref"] == "main"
        assert captured[0].get("sha") in (None, "")
    finally:
        db.close()


def test_clone_and_index_checks_out_existing_source_sha(monkeypatch):
    run_id, _repo = _seed_run(source_sha=TEST_SOURCE_SHA, ref=MOVED_REF)
    _approve(run_id, "sandbox_provision")
    captured = []
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: captured.append(kwargs) or (_fake_sandbox(), SOURCE_FILES),
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.install_project_dependencies",
        lambda sandbox: (0, "", ""),
    )
    monkeypatch.setattr(
        "app.workers.tasks.installation_token_for_repo",
        lambda *a, **k: "ghs_read",
    )
    monkeypatch.setattr(
        "app.workers.tasks.run_reproduction_test",
        lambda *a, **k: SimpleNamespace(
            reproduced=True,
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
    assert captured[0]["sha"] == TEST_SOURCE_SHA
    assert captured[0]["ref"] == MOVED_REF


def test_apply_patch_clones_source_sha_not_moved_ref(monkeypatch):
    run_id = _seed_apply_verify_run()
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        run.ref = MOVED_REF
        db.commit()
    finally:
        db.close()
    captured = []
    _stub_apply_verify(monkeypatch)
    _stub_failed_follow_on_suite(monkeypatch)
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: captured.append(kwargs) or (_fake_sandbox(), SOURCE_FILES),
    )
    monkeypatch.setattr(
        "app.workers.tasks.generate_patch",
        lambda **kwargs: "diff --git a/y b/y\n--- a/y\n+++ b/y\n",
    )
    apply_patch_and_verify.run(run_id)
    assert captured
    assert captured[0]["sha"] == TEST_SOURCE_SHA
    assert captured[0]["ref"] == MOVED_REF


def test_apply_patch_fails_closed_without_source_sha(monkeypatch):
    run_id, _repo = _seed_run(
        status="awaiting_patch_review",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        pipeline_stage="patch_review",
    )
    _approve(run_id, "patch_review")
    cloned = []
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: cloned.append(kwargs) or (_fake_sandbox(), SOURCE_FILES),
    )
    apply_patch_and_verify.run(run_id)
    assert cloned == []
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "failed"
        assert "source_sha is required" in (run.error or "")
    finally:
        db.close()


def _stub_pr_publish(monkeypatch, *, head_sha=TEST_SOURCE_SHA, parent_sha=TEST_SOURCE_SHA):
    cloned = []
    pushed = []
    prs = []
    monkeypatch.setattr(
        "app.workers.tasks.installation_token_for_repo",
        lambda *a, **k: "ghs_token",
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.clone_and_read_sources_in_sandbox",
        lambda **kwargs: cloned.append(kwargs) or (_fake_sandbox(), SOURCE_FILES),
    )
    monkeypatch.setattr(
        "app.workers.tasks.apply_diff_in_sandbox",
        lambda sandbox, diff: (True, None),
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.checkout_head_sha",
        lambda sandbox: head_sha,
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.run_sandbox_command",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.commit_parent_sha",
        lambda sandbox: parent_sha,
    )
    monkeypatch.setattr(
        "app.workers.tasks.e2b_runner.push_branch",
        lambda sandbox, branch, token: pushed.append((branch, token)),
    )
    monkeypatch.setattr(
        "app.workers.tasks.create_pull_request",
        lambda **kwargs: prs.append(kwargs) or {"html_url": "https://github.com/a/b/pull/1"},
    )
    monkeypatch.setattr("app.services.fcm.send_push", lambda *a, **k: "ok")
    return cloned, pushed, prs


def test_open_github_pr_binds_parent_and_keeps_ref_base(monkeypatch):
    run_id, _repo = _seed_run(
        status="awaiting_merge",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        pipeline_stage="merge",
        source_sha=TEST_SOURCE_SHA,
        ref="release",
    )
    _approve(run_id, "merge")
    cloned, pushed, prs = _stub_pr_publish(monkeypatch)
    open_github_pr.run(run_id)
    assert cloned[0]["sha"] == TEST_SOURCE_SHA
    assert cloned[0]["ref"] == "release"
    assert pushed
    assert prs[0]["base"] == "release"
    assert prs[0]["head"] == f"autopatch/run-{run_id}"
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "completed"
        assert run.pr_url.endswith("/pull/1")
        assert run.ref == "release"
        assert run.source_sha == TEST_SOURCE_SHA
    finally:
        db.close()


def test_open_github_pr_aborts_on_head_mismatch(monkeypatch):
    run_id, _repo = _seed_run(
        status="awaiting_merge",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        pipeline_stage="merge",
        source_sha=TEST_SOURCE_SHA,
    )
    _approve(run_id, "merge")
    cloned, pushed, prs = _stub_pr_publish(monkeypatch, head_sha=OTHER_SHA)
    try:
        open_github_pr.run(run_id)
    except RuntimeError as exc:
        assert "does not match source_sha" in str(exc)
    else:
        raise AssertionError("expected publication abort")
    assert cloned[0]["sha"] == TEST_SOURCE_SHA
    assert pushed == []
    assert prs == []


def test_open_github_pr_aborts_on_parent_mismatch(monkeypatch):
    run_id, _repo = _seed_run(
        status="awaiting_merge",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        pipeline_stage="merge",
        source_sha=TEST_SOURCE_SHA,
    )
    _approve(run_id, "merge")
    _cloned, pushed, prs = _stub_pr_publish(monkeypatch, parent_sha=OTHER_SHA)
    try:
        open_github_pr.run(run_id)
    except RuntimeError as circ:
        assert "patch commit parent" in str(circ)
    else:
        raise AssertionError("expected parent mismatch abort")
    assert pushed == []
    assert prs == []


def test_open_github_pr_fails_closed_without_source_sha(monkeypatch):
    run_id, _repo = _seed_run(
        status="awaiting_merge",
        current_diff="diff --git a/x b/x\n--- a/x\n+++ b/x\n",
        pipeline_stage="merge",
    )
    _approve(run_id, "merge")
    cloned, pushed, prs = _stub_pr_publish(monkeypatch)
    open_github_pr.run(run_id)
    assert cloned == []
    assert pushed == []
    assert prs == []
    db = SessionLocal()
    try:
        run = db.query(SandboxRun).filter(SandboxRun.id == run_id).one()
        assert run.status == "failed"
        assert "source_sha is required" in (run.error or "")
    finally:
        db.close()
