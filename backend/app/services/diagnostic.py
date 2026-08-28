from dataclasses import dataclass
import re

from app.services.stacktrace import StackFrame


@dataclass(frozen=True)
class DiagnosticLocation:
    path: str
    name: str
    kind: str
    start_line: int
    confidence: str


def locate_frames(
    frames: list[StackFrame],
    symbols: list[dict],
    sources: dict[str, str] | None = None,
) -> list[DiagnosticLocation]:

    results: list[DiagnosticLocation] = []

    for frame in frames:

        same_file = [
            symbol
            for symbol in symbols
            if symbol["path"] == frame.file
        ]

        if not same_file:
            continue

        # Strongest match:
        # same file + same function/class name.
        exact = [
            symbol
            for symbol in same_file
            if symbol["name"] == frame.function
        ]

        if exact:
            symbol = min(
                exact,
                key=lambda item: abs(
                    item["start_line"] - frame.line
                ),
            )

            results.append(
                DiagnosticLocation(
                    path=symbol["path"],
                    name=symbol["name"],
                    kind=symbol["kind"],
                    start_line=symbol["start_line"],
                    confidence="high",
                )
            )

            continue

        # Fallback:
        # find the nearest symbol that starts before
        # or exactly at the failing line.
        preceding = [
            symbol
            for symbol in same_file
            if symbol["start_line"] <= frame.line
        ]

        if not preceding:
            continue

        symbol = max(
            preceding,
            key=lambda item: item["start_line"],
        )

        results.append(
            DiagnosticLocation(
                path=symbol["path"],
                name=symbol["name"],
                kind=symbol["kind"],
                start_line=symbol["start_line"],
                confidence="medium",
            )
        )

    if not results and sources:
        from app.services.ripgrep import search_repo
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as root:
            for path, source in sources.items():
                dest = Path(root) / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(source, encoding="utf-8")
            for frame in frames:
                needle = frame.function or ""
                if not needle:
                    continue
                output = search_repo(root, needle)
                first = next(
                    (line for line in output.splitlines() if line.strip()),
                    "",
                )
                if not first:
                    continue
                match = re.search(r":(\d+):", first)
                if not match:
                    continue
                abs_path = first[: match.start()]
                try:
                    rel = Path(abs_path).resolve().relative_to(Path(root).resolve()).as_posix()
                except ValueError:
                    rel = Path(abs_path).as_posix()
                try:
                    line_no = int(match.group(1))
                except ValueError:
                    line_no = frame.line
                results.append(
                    DiagnosticLocation(
                        path=rel,
                        name=needle,
                        kind="function",
                        start_line=line_no,
                        confidence="low",
                    )
                )

    return results