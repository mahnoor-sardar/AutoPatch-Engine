from types import SimpleNamespace

from app.services.providers import (
    DISK_LIMIT_BYTES,
    E2BSession,
    apply_disk_quota,
    disk_quota_script,
)


def test_disk_quota_script_uses_loop_filesystem():
    script = disk_quota_script()
    assert "500M" in script or "count=500" in script
    assert "mount -o loop" in script
    assert "mkfs" in script
    assert "du -sb" not in script
    assert "chown" in script
    assert "$MNT/repo" in script
    assert "git clone" not in script


def test_disk_quota_script_gives_workspace_to_user_not_root_clone():
    script = disk_quota_script()
    assert 'APP_USER=user' in script
    assert "prepare_user_workspace" in script
    assert "chown \"$APP_USER:$APP_USER\" \"$MNT\"" in script
    assert 'id -u' in script
    assert "root is required" in script


def test_apply_disk_quota_is_fail_closed():
    class Boom:
        def run(self, command, timeout=120, **kwargs):
            raise RuntimeError("mkfs is required to enforce the 500MB sandbox disk quota")

    try:
        apply_disk_quota(Boom())
    except RuntimeError as exc:
        assert "500MB" in str(exc) or "mkfs" in str(exc)
        return
    raise AssertionError("expected disk quota setup to fail closed")


def test_session_write_file_enforces_500mb_cap():
    sandbox = SimpleNamespace(
        sandbox_id="quota-test",
        files=SimpleNamespace(
            write=lambda path, content: None,
            read=lambda path: "",
        ),
        commands=SimpleNamespace(run=lambda *a, **k: None),
        kill=lambda: None,
    )
    session = E2BSession(sandbox)
    session.write_file("/tmp/ok.txt", "ok")
    session._bytes_written = DISK_LIMIT_BYTES
    try:
        session.write_file("/tmp/over.txt", "x")
    except RuntimeError as exc:
        assert "disk write limit exceeded" in str(exc)
        return
    raise AssertionError("expected write over 500MB to be rejected")


def test_files_write_uses_the_same_quota():
    sandbox = SimpleNamespace(
        sandbox_id="quota-test",
        files=SimpleNamespace(
            write=lambda path, content: None,
            read=lambda path: "",
        ),
        commands=SimpleNamespace(run=lambda *a, **k: None),
        kill=lambda: None,
    )
    session = E2BSession(sandbox)
    session._bytes_written = DISK_LIMIT_BYTES
    try:
        session.files.write("/tmp/over.txt", "nope")
    except RuntimeError as exc:
        assert "disk write limit exceeded" in str(exc)
        return
    raise AssertionError("expected files.write to enforce the quota")
