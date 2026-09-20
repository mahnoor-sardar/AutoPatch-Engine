import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from app.services.patch_apply import (
    DIFF_PATH,
    REPO_ROOT,
    apply_diff_in_sandbox,
    patch_target_paths,
)

PHASE34_PATH = "backend/tests/fixtures/autopatch_phase34.py"
PHASE34_DIFF = (
    f"diff --git a/{PHASE34_PATH} b/{PHASE34_PATH}\n"
    f"--- a/{PHASE34_PATH}\n"
    f"+++ b/{PHASE34_PATH}\n"
    "@@ -1,2 +1,2 @@\n"
    " def reproduce_failure():\n"
    "-    return 1 / 0\n"
    "+    return 1\n"
)
NO_EOF_DIFF = (
    f"diff --git a/{PHASE34_PATH} b/{PHASE34_PATH}\n"
    f"--- a/{PHASE34_PATH}\n"
    f"+++ b/{PHASE34_PATH}\n"
    "@@ -1,2 +1,2 @@\n"
    " def reproduce_failure():\n"
    "-    return 1 / 0\n"
    "\\ No newline at end of file\n"
    "+    return 1\n"
    "\\ No newline at end of file\n"
)

MISSING_EOF = b"def reproduce_failure():\n    return 1 / 0"
WITH_EOF = MISSING_EOF + b"\n"
PATCHED_WITH_EOF = b"def reproduce_failure():\n    return 1\n"
PATCHED_NO_EOF = b"def reproduce_failure():\n    return 1"


def _text(path: Path) -> str:
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode()


def _git_env(repo: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_CEILING_DIRECTORIES"] = str(repo.parent.resolve())
    return env


def _init_repo(repo: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=repo,
        capture_output=True,
        check=True,
        env=_git_env(repo),
    )


def _git_apply(repo: Path, patch_file: Path, diff: str, check: bool = False) -> subprocess.CompletedProcess:
    patch_file.write_bytes(diff.encode("utf-8"))
    cmd = ["git", "apply"]
    if check:
        cmd.append("--check")
    cmd.append(str(patch_file))
    return subprocess.run(cmd, cwd=repo, capture_output=True, env=_git_env(repo))


def _repo_sandbox(repo: Path, patch_file: Path):
    writes = []

    class Sandbox:
        def write_file(self, path, content):
            writes.append(path)
            if path == DIFF_PATH:
                data = content.encode("utf-8") if isinstance(content, str) else content
                patch_file.write_bytes(data)
                return
            rel = path[len(REPO_ROOT.rstrip("/")) + 1 :]
            dest = repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(
                content.encode("utf-8") if isinstance(content, str) else content
            )

        def read_file(self, path):
            rel = path[len(REPO_ROOT.rstrip("/")) + 1 :]
            return (repo / rel).read_bytes().decode("utf-8")

    return Sandbox(), writes


def _wire_git(monkeypatch, repo: Path, patch_file: Path):
    def fake_run(sandbox, command, timeout):
        cmd = ["git", "apply"]
        if "git apply --check" in command:
            cmd.append("--check")
        cmd.append(str(patch_file))
        result = subprocess.run(
            cmd, cwd=repo, capture_output=True, env=_git_env(repo)
        )
        return SimpleNamespace(
            exit_code=result.returncode,
            stdout=result.stdout.decode("utf-8", "replace"),
            stderr=result.stderr.decode("utf-8", "replace"),
        )

    monkeypatch.setattr("app.services.patch_apply.run_sandbox_command", fake_run)


def test_patch_target_paths_from_unified_diff():
    assert patch_target_paths(PHASE34_DIFF) == [PHASE34_PATH]


def test_apply_does_not_pre_normalize_missing_eof(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    target = repo / PHASE34_PATH
    unrelated = repo / "backend" / "tests" / "fixtures" / "unrelated.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(MISSING_EOF)
    unrelated.write_bytes(b"keep = 1")
    _init_repo(repo)
    patch_file = tmp_path / "autopatch.diff"
    sandbox, writes = _repo_sandbox(repo, patch_file)
    _wire_git(monkeypatch, repo, patch_file)

    raw_repo = tmp_path / "raw-repo"
    raw_target = raw_repo / PHASE34_PATH
    raw_target.parent.mkdir(parents=True)
    raw_target.write_bytes(MISSING_EOF)
    _init_repo(raw_repo)
    raw = _git_apply(raw_repo, tmp_path / "raw.diff", PHASE34_DIFF)

    ok, err = apply_diff_in_sandbox(sandbox, PHASE34_DIFF, allowed_path=PHASE34_PATH)
    assert target.read_bytes() == raw_target.read_bytes()
    assert unrelated.read_bytes() == b"keep = 1"
    if raw.returncode == 0:
        assert ok is True
        assert err == ""
    else:
        assert ok is False
        assert target.read_bytes() == MISSING_EOF
    assert writes == [DIFF_PATH]


def test_existing_eof_newline_is_unchanged_by_helperless_apply(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    target = repo / PHASE34_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(WITH_EOF)
    _init_repo(repo)
    patch_file = tmp_path / "autopatch.diff"
    sandbox, writes = _repo_sandbox(repo, patch_file)
    _wire_git(monkeypatch, repo, patch_file)

    ok, err = apply_diff_in_sandbox(sandbox, PHASE34_DIFF, allowed_path=PHASE34_PATH)
    assert ok is True, err
    assert _text(target) == PATCHED_WITH_EOF.decode()
    assert writes == [DIFF_PATH]


def test_successful_apply_matches_raw_git_apply_without_extra_eof(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    target = repo / PHASE34_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(MISSING_EOF)
    _init_repo(repo)
    patch_file = tmp_path / "autopatch.diff"
    sandbox, writes = _repo_sandbox(repo, patch_file)
    _wire_git(monkeypatch, repo, patch_file)

    ok, err = apply_diff_in_sandbox(sandbox, NO_EOF_DIFF, allowed_path=PHASE34_PATH)
    assert ok is True, err

    raw_repo = tmp_path / "raw-repo"
    raw_target = raw_repo / PHASE34_PATH
    raw_target.parent.mkdir(parents=True)
    raw_target.write_bytes(MISSING_EOF)
    _init_repo(raw_repo)
    raw = _git_apply(raw_repo, tmp_path / "raw.diff", NO_EOF_DIFF)
    assert raw.returncode == 0, raw.stderr.decode("utf-8", "replace")
    assert _text(target) == _text(raw_target) == PATCHED_NO_EOF.decode()
    assert target.read_bytes().replace(b"\r\n", b"\n") == PATCHED_NO_EOF
    assert writes == [DIFF_PATH]
