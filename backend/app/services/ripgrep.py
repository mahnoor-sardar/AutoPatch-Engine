import shutil
import subprocess
import time
from pathlib import Path


class SearchTimedOut(Exception):
    """Raised when an in-memory search hits its deadline before finishing."""


def search_in_files(
    files: dict[str, str],
    pattern: str,
    *,
    max_hits: int | None = None,
    deadline: float | None = None,
    max_line_chars: int | None = None,
) -> list[tuple[str, int, str]]:
    """Search an in-memory path→source map. Never reads the filesystem.

    Optional bounds stop the scan between lines. A single ``re.search``
    call still cannot be preempted; callers should reject unsafe patterns.
    """
    import re

    compiled = re.compile(pattern)
    hits: list[tuple[str, int, str]] = []
    for path, source in files.items():
        if deadline is not None and time.monotonic() >= deadline:
            raise SearchTimedOut()
        text = source if isinstance(source, str) else ""
        for index, line in enumerate(text.splitlines(), 1):
            if deadline is not None and time.monotonic() >= deadline:
                raise SearchTimedOut()
            sample = line
            if max_line_chars is not None and len(sample) > max_line_chars:
                sample = sample[:max_line_chars]
            if compiled.search(sample):
                hits.append((path, index, sample))
                if max_hits is not None and len(hits) >= max_hits:
                    return hits
    return hits


def search_repo(root: str, pattern: str, glob: str | None = None) -> str:
    rg = shutil.which("rg")
    if rg is None:
        return _python_search(root, pattern, glob)

    command = [rg, "-n", "--hidden", "-S", pattern]
    if glob:
        command.extend(["-g", glob])
    command.append(root)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.stdout


def _python_search(root: str, pattern: str, glob: str | None) -> str:
    import re

    matches: list[str] = []
    root_path = Path(root)
    files = root_path.rglob(glob or "*") if glob else root_path.rglob("*")
    compiled = re.compile(pattern)
    for path in files:
        if not path.is_file():
            continue
        if "node_modules" in path.parts or ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for index, line in enumerate(text.splitlines(), 1):
            if compiled.search(line):
                matches.append(f"{path}:{index}:{line}")
    return "\n".join(matches)
