import shutil
import subprocess
from pathlib import Path


def search_in_files(
    files: dict[str, str], pattern: str
) -> list[tuple[str, int, str]]:
    import re

    compiled = re.compile(pattern)
    hits: list[tuple[str, int, str]] = []
    for path, source in files.items():
        for index, line in enumerate(source.splitlines(), 1):
            if compiled.search(line):
                hits.append((path, index, line))
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
