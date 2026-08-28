import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import ErrorIngest, Repository, SandboxRun
from app.schemas import ErrorIngestResponse, StackFrameOut
from app.services.approval import create_pending_provision_gate
from app.services.stacktrace import parse_stack_trace

router = APIRouter()


def _verify_signature(
    body: bytes,
    signature: str | None,
    secret: str,
) -> bool:
    if not signature or not secret:
        return False

    if signature.startswith("sha256="):
        signature = signature.removeprefix("sha256=")

    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(signature, expected)


def _string_field(payload: object, *keys: str) -> str | None:
    current: object = payload

    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)

    if isinstance(current, str) and current.strip():
        return current

    return None


def _sentry_values(payload: dict) -> list:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    data_error = (
        data.get("error") if data and isinstance(data.get("error"), dict) else None
    )
    data_event = (
        data.get("event") if data and isinstance(data.get("event"), dict) else None
    )
    for candidate in (
        payload,
        payload.get("event") if isinstance(payload.get("event"), dict) else None,
        data,
        data_error,
        data_event,
    ):
        if not isinstance(candidate, dict):
            continue

        exception = candidate.get("exception")

        if isinstance(exception, dict):
            values = exception.get("values")
            if isinstance(values, list) and values:
                return values

        if isinstance(exception, list) and exception:
            return exception

    return []


def _frames_to_stack_trace(
    frames: list,
    exception_type: str | None,
    message: str | None,
) -> str | None:
    lines = ["Traceback (most recent call last):"]
    wrote_frame = False

    for frame in frames:
        if not isinstance(frame, dict):
            continue

        file_path = (
            frame.get("filename")
            or frame.get("abs_path")
            or frame.get("file")
            or ""
        )
        line_no = frame.get("lineno") or frame.get("line") or 0
        function = frame.get("function") or "<unknown>"

        if isinstance(function, bool):
            function = "<unknown>"

        if not file_path:
            continue

        wrote_frame = True
        lines.append(
            f'  File "{file_path}", line {line_no}, in {function}'
        )

        context = frame.get("context_line")
        if isinstance(context, str) and context.strip():
            lines.append(f"    {context.strip()}")

    if not wrote_frame:
        return None

    if exception_type:
        if message:
            lines.append(f"{exception_type}: {message}")
        else:
            lines.append(str(exception_type))

    return "\n".join(lines)


def extract_stack_trace(payload: dict) -> str | None:
    for path in (
        ("stack_trace",),
        ("stacktrace",),
        ("traceback",),
        ("error", "stack"),
        ("error", "stack_trace"),
        ("error", "traceback"),
        ("event", "stack_trace"),
        ("data", "error", "stack"),
    ):
        value = _string_field(payload, *path)
        if value:
            return value

    values = _sentry_values(payload)

    if values:
        first = values[0] if isinstance(values[0], dict) else {}
        stacktrace = first.get("stacktrace") if isinstance(first, dict) else None
        frames = (
            stacktrace.get("frames")
            if isinstance(stacktrace, dict)
            else None
        )
        exception_type = first.get("type") if isinstance(first, dict) else None
        message = first.get("value") if isinstance(first, dict) else None

        if isinstance(frames, list):
            converted = _frames_to_stack_trace(
                frames,
                exception_type if isinstance(exception_type, str) else None,
                message if isinstance(message, str) else None,
            )
            if converted:
                return converted

        if isinstance(exception_type, str) and exception_type.strip():
            if isinstance(message, str) and message.strip():
                return f"{exception_type}: {message}"
            return exception_type

    return None


def _repo_from_tag_dict(tags: object) -> str | None:
    if not isinstance(tags, dict):
        return None
    repo = tags.get("repo") or tags.get("repository")
    if isinstance(repo, str) and "/" in repo:
        return repo
    return None


def _repo_from_tag_list(tags: object) -> str | None:
    if not isinstance(tags, list):
        return None
    for item in tags:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        key, value = item[0], item[1]
        if key == "repo" and isinstance(value, str) and "/" in value:
            return value
    return None


def _sentry_tag_containers(payload: dict) -> list:
    containers: list = [payload.get("tags")]
    event = payload.get("event")
    if isinstance(event, dict):
        containers.append(event.get("tags"))
    data = payload.get("data")
    if isinstance(data, dict):
        containers.append(data.get("tags"))
        error = data.get("error")
        if isinstance(error, dict):
            containers.append(error.get("tags"))
        nested_event = data.get("event")
        if isinstance(nested_event, dict):
            containers.append(nested_event.get("tags"))
    return containers


def _payload_repo(payload: dict, *, provider: str | None = None) -> str | None:
    repo = payload.get("repo") or payload.get("repository")
    if isinstance(repo, dict):
        repo = repo.get("full_name") or repo.get("name")
    if isinstance(repo, str) and "/" in repo:
        return repo

    found = _repo_from_tag_dict(payload.get("tags"))
    if found:
        return found

    if provider != "sentry":
        return None

    for tags in _sentry_tag_containers(payload):
        found = _repo_from_tag_dict(tags) or _repo_from_tag_list(tags)
        if found:
            return found
    return None


def _maybe_start_run(
    db: Session, payload: dict, stack_trace: str, provider: str
) -> None:
    repo_name = _payload_repo(payload, provider=provider)
    if not repo_name:
        return
    repo = (
        db.query(Repository)
        .filter(Repository.full_name == repo_name)
        .one_or_none()
    )
    if repo is None:
        return
    ref = payload.get("ref") or repo.default_branch
    run = SandboxRun(
        status="queued",
        repo=repo.full_name,
        ref=ref if isinstance(ref, str) else repo.default_branch,
        stack_trace=stack_trace,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    create_pending_provision_gate(db, run)


def _ingest(
    body: bytes,
    signature: str | None,
    secret: str,
    provider: str,
    db: Session,
) -> ErrorIngestResponse:
    if not _verify_signature(body, signature, secret):
        raise HTTPException(
            status_code=401,
            detail="invalid signature",
        )

    try:
        payload = json.loads(body or b"")
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="malformed payload",
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="malformed payload",
        )

    stack_trace = extract_stack_trace(payload)

    if not stack_trace:
        raise HTTPException(
            status_code=400,
            detail="no extractable stack trace",
        )

    parsed = parse_stack_trace(stack_trace)

    row = ErrorIngest(
        provider=provider,
        stack_trace=stack_trace,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    _maybe_start_run(db, payload, stack_trace, provider)

    return ErrorIngestResponse(
        provider=provider,
        id=row.id,
        exception_type=parsed.exception_type,
        message=parsed.message,
        frames=[
            StackFrameOut(
                file=frame.file,
                line=frame.line,
                function=frame.function,
            )
            for frame in parsed.frames
        ],
    )


@router.post("/v1/webhooks/sentry")
async def sentry_webhook(
    request: Request,
    db: Session = Depends(get_db),
    sentry_hook_signature: str | None = Header(
        default=None,
        alias="Sentry-Hook-Signature",
    ),
    x_sentry_hook_signature: str | None = Header(default=None),
):
    body = await request.body()
    signature = sentry_hook_signature or x_sentry_hook_signature

    return _ingest(
        body,
        signature,
        settings.sentry_webhook_secret,
        "sentry",
        db,
    )


@router.post("/v1/webhooks/datadog")
async def datadog_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_datadog_signature: str | None = Header(default=None),
):
    body = await request.body()

    return _ingest(
        body,
        x_datadog_signature,
        settings.datadog_webhook_secret,
        "datadog",
        db,
    )
