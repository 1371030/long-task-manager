from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    constraints: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="intake", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    current_revision_id: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str | None] = mapped_column(String(255), default="user")
    executor_mode: Mapped[str] = mapped_column(String(50), default="agent", nullable=False)
    project_path: Mapped[str | None] = mapped_column(Text)
    codex_tmux_session: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    messages: Mapped[list["TaskMessage"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    revisions: Mapped[list["TaskRevision"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    steps: Mapped[list["Step"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    runs: Mapped[list["StepRun"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    events: Mapped[list["Event"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    capability_invocations: Mapped[list["CapabilityInvocation"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    progress_reviews: Mapped[list["TaskReview"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class TaskMessage(Base):
    __tablename__ = "task_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    author_type: Mapped[str] = mapped_column(String(50), default="human", nullable=False)
    author_id: Mapped[str | None] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    constraints: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    task: Mapped[Task] = relationship(back_populates="messages")


class TaskRevision(Base):
    __tablename__ = "task_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_type: Mapped[str] = mapped_column(String(50), default="system", nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    task: Mapped[Task] = relationship(back_populates="revisions")


class TaskReview(Base):
    __tablename__ = "task_progress_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    previous_review_id: Mapped[int | None] = mapped_column(ForeignKey("task_progress_reviews.id"))
    expected_progress_percent: Mapped[float] = mapped_column(Float, nullable=False)
    actual_progress_percent: Mapped[float] = mapped_column(Float, nullable=False)
    variance_percentage_points: Mapped[float] = mapped_column(Float, nullable=False)
    classification: Mapped[str] = mapped_column(String(50), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    observations_json: Mapped[str] = mapped_column(Text, nullable=False)
    suggestions_json: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str | None] = mapped_column(String(50))
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_by_type: Mapped[str | None] = mapped_column(String(50))
    decided_by_id: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_type: Mapped[str] = mapped_column(String(50), default="human", nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    task: Mapped[Task] = relationship(back_populates="progress_reviews")
    previous_review: Mapped["TaskReview | None"] = relationship(remote_side=[id])


class StepComparisonGroup(Base):
    __tablename__ = "step_comparison_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    origin_step_id: Mapped[int | None] = mapped_column(Integer)
    base_step_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    selection_status: Mapped[str] = mapped_column(String(50), default="open", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="open", nullable=False)
    selected_step_id: Mapped[int | None] = mapped_column(Integer)
    created_reason: Mapped[str | None] = mapped_column(Text)
    created_by_type: Mapped[str] = mapped_column(String(50), default="system", nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Step(Base):
    __tablename__ = "task_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    parent_step_id: Mapped[int | None] = mapped_column(ForeignKey("task_steps.id"))
    comparison_group_id: Mapped[int | None] = mapped_column(ForeignKey("step_comparison_groups.id"))
    approved_run_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    depends_on_step_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    previous_step_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    next_step_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_dynamic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_reason: Mapped[str | None] = mapped_column(Text)
    created_by_type: Mapped[str] = mapped_column(String(50), default="system", nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String(255))
    inserted_after_step_id: Mapped[int | None] = mapped_column(Integer)
    supersedes_step_id: Mapped[int | None] = mapped_column(Integer)
    superseded_by_step_id: Mapped[int | None] = mapped_column(Integer)
    executor_hint: Mapped[str | None] = mapped_column(String(255))
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_attempts: Mapped[int | None] = mapped_column(Integer)
    variant_label: Mapped[str | None] = mapped_column(String(255))
    selected_variant: Mapped[bool | None] = mapped_column(Boolean)
    is_fork: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    forked_from_step_id: Mapped[int | None] = mapped_column(Integer)
    forked_from_run_id: Mapped[int | None] = mapped_column(Integer)
    fork_reason: Mapped[str | None] = mapped_column(Text)
    branch_status: Mapped[str | None] = mapped_column(String(50))
    cloned_from_step_id: Mapped[int | None] = mapped_column(Integer)
    clone_batch_id: Mapped[str | None] = mapped_column(String(255))
    is_selected_variant: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    task: Mapped[Task] = relationship(back_populates="steps")
    parent_step: Mapped["Step | None"] = relationship(remote_side=[id])
    runs: Mapped[list["StepRun"]] = relationship(back_populates="step", cascade="all, delete-orphan")


class StepRun(Base):
    __tablename__ = "step_runs"
    __table_args__ = (UniqueConstraint("step_id", "attempt_number", name="uq_step_attempt_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("task_steps.id"), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    executor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    executor_ref: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="running", nullable=False)
    input: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    output: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    task: Mapped[Task] = relationship(back_populates="runs")
    step: Mapped[Step] = relationship(back_populates="runs")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    capability_invocations: Mapped[list["CapabilityInvocation"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class CapabilityInvocation(Base):
    __tablename__ = "capability_invocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    step_id: Mapped[int | None] = mapped_column(ForeignKey("task_steps.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("step_runs.id"))
    invoked_by_type: Mapped[str] = mapped_column(String(50), nullable=False)
    invoked_by_id: Mapped[str | None] = mapped_column(String(255))
    capability_id: Mapped[str] = mapped_column(String(255), nullable=False)
    capability_name: Mapped[str | None] = mapped_column(String(255))
    adapter_id: Mapped[str | None] = mapped_column(String(255))
    handler_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    input: Mapped[str | None] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    artifacts_json: Mapped[str | None] = mapped_column("artifacts", Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped[Task] = relationship(back_populates="capability_invocations")
    run: Mapped[StepRun | None] = relationship(back_populates="capability_invocations")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    step_id: Mapped[int | None] = mapped_column(ForeignKey("task_steps.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("step_runs.id"))
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    reviewed_by_type: Mapped[str] = mapped_column(String(50), default="human", nullable=False)
    reviewed_by_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    task: Mapped[Task] = relationship(back_populates="approvals")
    run: Mapped[StepRun | None] = relationship(back_populates="approvals")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    step_id: Mapped[int | None] = mapped_column(ForeignKey("task_steps.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("step_runs.id"))
    capability_invocation_id: Mapped[int | None] = mapped_column(ForeignKey("capability_invocations.id"))
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    uri: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    task: Mapped[Task] = relationship(back_populates="artifacts")


class Event(Base):
    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    step_id: Mapped[int | None] = mapped_column(ForeignKey("task_steps.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("step_runs.id"))
    capability_invocation_id: Mapped[int | None] = mapped_column(ForeignKey("capability_invocations.id"))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    task: Mapped[Task] = relationship(back_populates="events")
