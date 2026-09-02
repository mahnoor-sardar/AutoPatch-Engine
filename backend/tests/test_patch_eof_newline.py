import subprocess
from pathlib import Path

from app.services.patch_apply import (
    ensure_eof_newline_on_patch_targets,
    patch_target_paths,
)

PHASE34_DIFF = (
    "--- a/backend/tests/fixtures/autopatch_phase34.py\n"
    "+++ b/backend/tests/fixtures/autopatch_phase34.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def reproduce_failure():\n"
    "-    return 1 / 0\n"
    "+    return 1\n"
)

MISSING_EOF = b"def reproduce_failure():\n    return 1 / 0"
PATCHED_TEXT = "def reproduce_failure():\n    return 1\n"


def _text(path: Path) -> str:
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n").decode()


def test_patch_target_paths_from_unified_diff():
    assert patch_target_paths(PHASE34_DIFF) == [
        "backend/tests/fixtures/autopatch_phase34.py"
    ]


def test_missing_eof_newline_accepts_generated_diff(tmp_path):
    repo = tmp_path / "repo"
    target = repo / "backend" / "tests" / "fixtures" / "autopatch_phase34.py"
    unrelated = repo / "backend" / "tests" / "fixtures" / "unrelated.py"
    already = repo / "backend" / "app" / "already_nl.py"
    target.parent.mkdir(parents=True)
    already.parent.mkdir(parents=True)
    target.write_bytes(MISSING_EOF)
    unrelated.write_bytes(b"keep = 1")
    already.write_bytes(b"x = 1\n")

    changed = ensure_eof_newline_on_patch_targets(repo, PHASE34_DIFF)
    assert changed == ["backend/tests/fixtures/autopatch_phase34.py"]
    assert target.read_bytes() == MISSING_EOF + b"\n"
    assert unrelated.read_bytes() == b"keep = 1"
    assert already.read_bytes() == b"x = 1\n"

    applied = _git_apply(repo, tmp_path / "autopatch.diff")
    assert applied.returncode == 0, applied.stderr
    assert _text(target) == PATCHED_TEXT
    assert unrelated.read_bytes() == b"keep = 1"
    assert already.read_bytes() == b"x = 1\n"


def test_existing_eof_newline_is_unchanged(tmp_path):
    repo = tmp_path / "repo"
    target = repo / "backend" / "tests" / "fixtures" / "autopatch_phase34.py"
    target.parent.mkdir(parents=True)
    original = MISSING_EOF + b"\n"
    target.write_bytes(original)
    assert ensure_eof_newline_on_patch_targets(repo, PHASE34_DIFF) == []
    assert target.read_bytes() == original

    applied = _git_apply(repo, tmp_path / "autopatch.diff")
    assert applied.returncode == 0, applied.stderr
    assert _text(target) == PATCHED_TEXT


def _git_apply(repo: Path, patch_file: Path) -> subprocess.CompletedProcess:
    patch_file.write_bytes(PHASE34_DIFF.encode("utf-8"))
    return subprocess.run(
        ["git", "apply", str(patch_file)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
