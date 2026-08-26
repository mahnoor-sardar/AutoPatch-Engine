import re
from dataclasses import dataclass


@dataclass(frozen=True)
class StackFrame:
    file: str
    line: int
    function: str


@dataclass(frozen=True)
class StackTrace:
    frames: list[StackFrame]
    exception_type: str | None
    message: str | None


_FRAME_PATTERN = re.compile(
    r'^\s*File "(.+)", line (\d+), in (.+)$'
)

_EXCEPTION_PATTERN = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_.]*)(?::\s*(.*))?$"
)


def parse_stack_trace(trace: str) -> StackTrace:
    frames: list[StackFrame] = []

    lines = trace.splitlines()

    for line in lines:
        match = _FRAME_PATTERN.match(line)

        if match is None:
            continue

        file_path, line_number, function = match.groups()

        frames.append(
            StackFrame(
                file=file_path,
                line=int(line_number),
                function=function.strip(),
            )
        )

    exception_type: str | None = None
    message: str | None = None

    for line in reversed(lines):
        stripped = line.strip()

        if not stripped:
            continue

        match = _EXCEPTION_PATTERN.match(stripped)

        if match is None:
            continue

        candidate_type, candidate_message = match.groups()

        if candidate_type in {
            "Traceback",
            "File",
        }:
            continue

        if not (
            candidate_type.endswith("Error")
            or candidate_type.endswith("Exception")
            or "." in candidate_type
        ):
            continue

        exception_type = candidate_type
        message = candidate_message
        break

    return StackTrace(
        frames=frames,
        exception_type=exception_type,
        message=message,
    )