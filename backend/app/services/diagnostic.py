from dataclasses import dataclass

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

    return results