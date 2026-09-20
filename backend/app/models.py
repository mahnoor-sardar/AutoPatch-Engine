from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class GitHubInstallation(Base):
    __tablename__ = "github_installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        index=True,
    )
    account_login: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    repositories: Mapped[list["Repository"]] = relationship(
        back_populates="installation"
    )


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
    )
    installation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("github_installations.installation_id"),
    )
    default_branch: Mapped[str] = mapped_column(
        String(255),
        default="main",
    )

    installation: Mapped[GitHubInstallation] = relationship(
        back_populates="repositories"
    )


class SandboxRun(Base):
    __tablename__ = "sandbox_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    status: Mapped[str] = mapped_column(
        String(32),
        default="queued",
    )

    e2b_sandbox_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    repo: Mapped[str] = mapped_column(
        String(255)
    )

    ref: Mapped[str] = mapped_column(
        String(255),
        default="main",
    )

    source_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )

    stack_trace: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    current_diff: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    patch_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    llm_tokens_used: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    pr_url: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )

    control_state: Mapped[str] = mapped_column(
        String(32),
        default="active",
    )

    pipeline_stage: Mapped[str] = mapped_column(
        String(32),
        default="provision",
    )

    stage_owner_token: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    stage_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    approval_gates: Mapped[list["ApprovalGate"]] = relationship(
        back_populates="run"
    )

    symbols: Mapped[list["Symbol"]] = relationship(
        back_populates="run"
    )

    reproduction_attempts: Mapped[
        list["ReproductionAttempt"]
    ] = relationship(
        back_populates="run"
    )

    patch_records: Mapped[list["PatchAttempt"]] = relationship(
        back_populates="run"
    )

    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="run"
    )


class ApprovalGate(Base):
    __tablename__ = "approval_gates"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    run_id: Mapped[int] = mapped_column(
        ForeignKey("sandbox_runs.id"),
        index=True,
    )

    gate: Mapped[str] = mapped_column(
        String(32)
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
    )

    device_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    run: Mapped[SandboxRun] = relationship(
        back_populates="approval_gates"
    )


class Symbol(Base):
    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    run_id: Mapped[int] = mapped_column(
        ForeignKey("sandbox_runs.id"),
        index=True,
    )

    path: Mapped[str] = mapped_column(
        String(1024)
    )

    name: Mapped[str] = mapped_column(
        String(255),
        index=True,
    )

    embedding: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    kind: Mapped[str] = mapped_column(
        String(64)
    )

    start_line: Mapped[int] = mapped_column(
        Integer
    )

    run: Mapped[SandboxRun] = relationship(
        back_populates="symbols"
    )


class DeviceAuthReplay(Base):
    __tablename__ = "device_auth_replays"
    __table_args__ = (
        UniqueConstraint(
            "device_id",
            "action_key",
            "credential_hash",
            name="uq_device_auth_replay",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True)
    action_key: Mapped[str] = mapped_column(String(256))
    credential_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    device_id: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True,
    )

    fcm_token: Mapped[str] = mapped_column(
        Text
    )

    totp_secret: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    label: Mapped[str] = mapped_column(
        String(255),
        default="",
    )

    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class PushEvent(Base):
    __tablename__ = "push_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    device_id: Mapped[str] = mapped_column(
        String(128),
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255)
    )

    status: Mapped[str] = mapped_column(
        String(32)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class ReproductionAttempt(Base):
    __tablename__ = "reproduction_attempts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    run_id: Mapped[int] = mapped_column(
        ForeignKey("sandbox_runs.id"),
        index=True,
    )

    stack_trace: Mapped[str] = mapped_column(
        Text
    )

    diagnostic_path: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    diagnostic_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    diagnostic_line: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    test_path: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    test_source: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    exit_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    stdout: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    stderr: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    reproduced: Mapped[bool] = mapped_column(
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    run: Mapped[SandboxRun] = relationship(
        back_populates="reproduction_attempts"
    )


class PatchAttempt(Base):
    __tablename__ = "patch_attempts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    run_id: Mapped[int] = mapped_column(
        ForeignKey("sandbox_runs.id"),
        index=True,
    )

    attempt_number: Mapped[int] = mapped_column(
        Integer
    )

    diff: Mapped[str] = mapped_column(
        Text
    )

    status: Mapped[str] = mapped_column(
        String(32),
        default="pending_review",
    )

    stdout: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    stderr: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    run: Mapped[SandboxRun] = relationship(
        back_populates="patch_records"
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sandbox_runs.id"),
        index=True,
        nullable=True,
    )

    device_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    action: Mapped[str] = mapped_column(
        String(64)
    )

    actor: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    result: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    detail: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    event_metadata: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    run: Mapped[SandboxRun | None] = relationship(
        back_populates="audit_events"
    )


class ErrorIngest(Base):
    __tablename__ = "error_ingests"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    provider: Mapped[str] = mapped_column(
        String(32)
    )

    stack_trace: Mapped[str] = mapped_column(
        Text
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )