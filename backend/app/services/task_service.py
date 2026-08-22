import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import settings
from . import settings_service
from .next_action_service import build_current_pointer, build_next_actions, next_startable_step as next_startable_ordered_step
from .plan_generation_service import generate_plan_steps, plan_llm_call_payload
from .progress_service import compute_progress, progress_eligible_steps, run_consumed_ms

VALID_EXECUTOR_TYPES = {"human", "agent", "worker", "system", "codex"}
STEP_MUTATION_TASK_STATUSES = {"intake", "planning", "waiting_plan_review", "planned", "running", "waiting_review", "needs_revision", "blocked", "failed"}
STARTABLE_STEP_STATUSES = {"pending", "needs_revision", "failed"}
IN_PLACE_RETRY_STEP_STATUSES = {"approved", "needs_revision", "failed"}
RERUNNABLE_STEP_STATUSES = {"approved", "needs_revision", "failed", "skipped"}
COMPLETED_STEP_STATUSES = {"approved", "skipped"}
EXCLUDED_BRANCH_STATUSES = {"not_selected", "abandoned", "superseded"}
TASK_LOG_DIR = Path(__file__).resolve().parents[3] / "task_logs"
SENSITIVE_LOG_KEYS = ("password", "token", "secret", "api_key", "authorization", "cookie", "credential", "private_key")
SENSITIVE_LOG_PATTERN = re.compile(r"(?i)(password|token|secret|api_key|authorization|cookie|credential|private_key)(\s*[=:]\s*)([^\s,;&]+)")
LOG_STRING_LIMIT = 8000


def truncate_log_string(value: str) -> str:
    if len(value) <= LOG_STRING_LIMIT:
        return value
    return f"{value[:LOG_STRING_LIMIT]}... [truncated {len(value) - LOG_STRING_LIMIT} chars]"


def redact_log_string(value: str, include_sensitive: bool) -> str:
    truncated = truncate_log_string(value)
    if include_sensitive:
        return truncated
    return SENSITIVE_LOG_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", truncated)


def redact_log_value(value: Any, include_sensitive: bool) -> Any:
    if include_sensitive:
        if isinstance(value, str):
            return redact_log_string(value, include_sensitive)
        if isinstance(value, list):
            return [redact_log_value(item, include_sensitive) for item in value]
        if isinstance(value, dict):
            return {key: redact_log_value(item, include_sensitive) for key, item in value.items()}
        return value
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            redacted[key] = "[REDACTED]" if any(marker in lowered for marker in SENSITIVE_LOG_KEYS) else redact_log_value(item, include_sensitive)
        return redacted
    if isinstance(value, list):
        return [redact_log_value(item, include_sensitive) for item in value]
    if isinstance(value, str):
        return redact_log_string(value, include_sensitive)
    return value


def log_entry_sort_key(entry: schemas.TaskLogEntry) -> tuple[str, str]:
    return ((entry.timestamp.isoformat() if entry.timestamp else ""), entry.id)


def summarize_log_value(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("summary", "message", "status", "title", "reason"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        if value:
            return f"keys: {', '.join(value.keys())}"
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def encode_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def decode_json(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)



def task_context_entries(task: models.Task, include_sensitive: bool) -> list[schemas.TaskLogEntry]:
    entries = [
        schemas.TaskLogEntry(
            id=f"task:{task.id}",
            timestamp=task.created_at,
            scope="task",
            event_type="task_snapshot",
            title=f"Task {task.id}: {task.title}",
            message=task.goal,
            task_id=task.id,
            status=task.status,
            metadata=redact_log_value(
                {
                    "constraints": task.constraints,
                    "summary": task.summary,
                    "current_revision_id": task.current_revision_id,
                    "created_by": task.created_by,
                    "executor_mode": task.executor_mode,
                    "project_path": task.project_path,
                    "codex_tmux_session": task.codex_tmux_session,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                },
                include_sensitive,
            ),
            redacted=not include_sensitive,
        )
    ]
    for message in sorted(task.messages, key=lambda item: (item.created_at, item.id)):
        entries.append(
            schemas.TaskLogEntry(
                id=f"message:{message.id}",
                timestamp=message.created_at,
                scope="task",
                event_type="task_message",
                title=f"Task message from {message.author_type}",
                message=redact_log_string(message.message, include_sensitive),
                task_id=task.id,
                metadata=redact_log_value(
                    {"author_type": message.author_type, "author_id": message.author_id, "constraints": message.constraints},
                    include_sensitive,
                ),
                redacted=not include_sensitive,
            )
        )
    for revision in sorted(task.revisions, key=lambda item: (item.created_at, item.id)):
        entries.append(
            schemas.TaskLogEntry(
                id=f"revision:{revision.id}",
                timestamp=revision.created_at,
                scope="task",
                event_type="task_revision",
                title=f"Plan revision {revision.revision_number}",
                message=revision.reason,
                task_id=task.id,
                metadata={"created_by_type": revision.created_by_type, "created_by_id": revision.created_by_id},
            )
        )
    return entries


def step_log_entry(step: models.Step, include_sensitive: bool) -> schemas.TaskLogEntry:
    return schemas.TaskLogEntry(
        id=f"step:{step.id}",
        timestamp=step.created_at,
        scope="step",
        event_type="step_snapshot",
        title=f"Step {step.step_order}: {step.title}",
        message=step.objective,
        task_id=step.task_id,
        step_id=step.id,
        status=step.status,
        metadata=redact_log_value(
            {
                "position": step.position,
                "depends_on_step_ids": step.depends_on_step_ids,
                "is_active": step.is_active,
                "is_dynamic": step.is_dynamic,
                "created_reason": step.created_reason,
                "created_by_type": step.created_by_type,
                "created_by_id": step.created_by_id,
                "approved_run_id": step.approved_run_id,
                "requires_approval": step.requires_approval,
                "max_attempts": step.max_attempts,
                "variant_label": step.variant_label,
                "branch_status": step.branch_status,
                "updated_at": step.updated_at.isoformat() if step.updated_at else None,
            },
            include_sensitive,
        ),
        redacted=not include_sensitive,
    )


def run_log_entry(run: models.StepRun, include_sensitive: bool) -> schemas.TaskLogEntry:
    output = decode_json(run.output)
    input_payload = decode_json(run.input) or {}
    return schemas.TaskLogEntry(
        id=f"run:{run.id}",
        timestamp=run.started_at or run.created_at,
        scope="run",
        event_type="run_snapshot",
        title=f"Run {run.id} attempt {run.attempt_number}",
        message=summarize_log_value(output) or run.error,
        task_id=run.task_id,
        step_id=run.step_id,
        run_id=run.id,
        status=run.status,
        duration_ms=run_consumed_ms(run, models.utcnow()),
        input=redact_log_value(input_payload, include_sensitive),
        output=redact_log_value(output, include_sensitive) if isinstance(output, dict) else None,
        error=run.error,
        metadata=redact_log_value(
            {
                "executor_type": run.executor_type,
                "executor_ref": run.executor_ref,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "submitted_at": run.submitted_at.isoformat() if run.submitted_at else None,
                "ended_at": run.ended_at.isoformat() if run.ended_at else None,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "updated_at": run.updated_at.isoformat() if run.updated_at else None,
            },
            include_sensitive,
        ),
        redacted=not include_sensitive,
    )


def event_log_entry(event: models.Event, include_sensitive: bool) -> schemas.TaskLogEntry:
    payload = decode_json(event.payload) or {}
    if event.event_type == "progress_recalculated":
        scope = "progress"
    elif event.capability_invocation_id is not None:
        scope = "capability_invocation"
    elif event.run_id is not None:
        scope = "run"
    elif event.step_id is not None:
        scope = "step"
    else:
        scope = "task"
    return schemas.TaskLogEntry(
        id=f"event:{event.id}",
        timestamp=event.created_at,
        scope=scope,
        event_type=event.event_type,
        title=event.event_type.replace("_", " ").title(),
        message=summarize_log_value(payload),
        task_id=event.task_id,
        step_id=event.step_id,
        run_id=event.run_id,
        capability_invocation_id=event.capability_invocation_id,
        status=payload.get("status") if isinstance(payload.get("status"), str) else None,
        duration_ms=payload.get("duration_ms") if isinstance(payload.get("duration_ms"), int) else None,
        metadata=redact_log_value(payload, include_sensitive),
        redacted=not include_sensitive,
    )


def artifact_log_entry(artifact: models.Artifact, include_sensitive: bool) -> schemas.TaskLogEntry:
    metadata = decode_json(artifact.metadata_json) or {}
    return schemas.TaskLogEntry(
        id=f"artifact:{artifact.id}",
        timestamp=artifact.created_at,
        scope="artifact",
        event_type="artifact_snapshot",
        title=f"Artifact {artifact.id}: {artifact.name}",
        message=artifact.uri,
        task_id=artifact.task_id,
        step_id=artifact.step_id,
        run_id=artifact.run_id,
        capability_invocation_id=artifact.capability_invocation_id,
        artifact_id=artifact.id,
        metadata=redact_log_value({"type": artifact.type, "uri": artifact.uri, "metadata": metadata}, include_sensitive),
        redacted=not include_sensitive,
    )


def capability_invocation_log_entry(invocation: models.CapabilityInvocation, include_sensitive: bool) -> schemas.TaskLogEntry:
    output = decode_json(invocation.output)
    input_payload = decode_json(invocation.input) or {}
    return schemas.TaskLogEntry(
        id=f"capability:{invocation.id}",
        timestamp=invocation.created_at,
        scope="capability_invocation",
        event_type="capability_invocation_snapshot",
        title=f"Capability {invocation.capability_id}",
        message=summarize_log_value(output) or invocation.error,
        task_id=invocation.task_id,
        step_id=invocation.step_id,
        run_id=invocation.run_id,
        capability_invocation_id=invocation.id,
        status=invocation.status,
        duration_ms=invocation.duration_ms,
        input=redact_log_value(input_payload, include_sensitive),
        output=redact_log_value(output, include_sensitive) if isinstance(output, dict) else None,
        error=invocation.error,
        metadata=redact_log_value(
            {
                "capability_name": invocation.capability_name,
                "adapter_id": invocation.adapter_id,
                "handler_name": invocation.handler_name,
                "invoked_by_type": invocation.invoked_by_type,
                "invoked_by_id": invocation.invoked_by_id,
                "artifacts": decode_json(invocation.artifacts_json) or [],
                "completed_at": invocation.completed_at.isoformat() if invocation.completed_at else None,
                "ended_at": invocation.ended_at.isoformat() if invocation.ended_at else None,
            },
            include_sensitive,
        ),
        redacted=not include_sensitive,
    )


def approval_log_entry(approval: models.Approval, include_sensitive: bool) -> schemas.TaskLogEntry:
    return schemas.TaskLogEntry(
        id=f"approval:{approval.id}",
        timestamp=approval.created_at,
        scope="run" if approval.run_id is not None else "task",
        event_type="approval_snapshot",
        title=f"Review decision: {approval.decision}",
        message=approval.comment,
        task_id=approval.task_id,
        step_id=approval.step_id,
        run_id=approval.run_id,
        status=approval.decision,
        metadata=redact_log_value(
            {"reviewed_by_type": approval.reviewed_by_type, "reviewed_by_id": approval.reviewed_by_id},
            include_sensitive,
        ),
        redacted=not include_sensitive,
    )


def include_log_entry(entry: schemas.TaskLogEntry, step_id: int | None, run_id: int | None, context_step_ids: set[int]) -> bool:
    if run_id is not None:
        return entry.scope == "task" or entry.run_id == run_id or (entry.scope == "step" and entry.step_id in context_step_ids)
    if step_id is not None:
        return entry.scope == "task" or entry.step_id == step_id
    return True


def render_execution_log_text(task: models.Task, entries: list[schemas.TaskLogEntry]) -> str:
    lines = [f"Execution log: {task.title}", f"Task ID: {task.id}", f"Status: {task.status}", ""]
    for entry in entries:
        timestamp = entry.timestamp.isoformat() if entry.timestamp else "unknown time"
        refs = []
        if entry.step_id is not None:
            refs.append(f"step={entry.step_id}")
        if entry.run_id is not None:
            refs.append(f"run={entry.run_id}")
        if entry.capability_invocation_id is not None:
            refs.append(f"capability={entry.capability_invocation_id}")
        if entry.artifact_id is not None:
            refs.append(f"artifact={entry.artifact_id}")
        suffix = f" ({', '.join(refs)})" if refs else ""
        lines.append(f"[{timestamp}] {entry.title}{suffix}")
        lines.append(f"scope={entry.scope}")
        lines.append(f"event={entry.event_type}")
        if entry.status is not None:
            lines.append(f"status={entry.status}")
        if entry.duration_ms is not None:
            lines.append(f"duration_ms={entry.duration_ms}")
        if entry.message:
            lines.append(f"message={redact_log_string(entry.message, entry.redacted is False)}")
        if entry.error:
            lines.append(f"error={redact_log_string(entry.error, entry.redacted is False)}")
        if entry.input is not None:
            lines.append(f"input={json.dumps(entry.input, ensure_ascii=False)}")
        if entry.output is not None:
            lines.append(f"output={json.dumps(entry.output, ensure_ascii=False)}")
        if entry.metadata:
            lines.append(f"metadata={json.dumps(entry.metadata, ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def generate_task_execution_log_text(
    db: Session,
    task_id: int,
    step_id: int | None = None,
    run_id: int | None = None,
    include_sensitive: bool = False,
) -> str:
    task = get_task_or_404(db, task_id)
    if step_id is not None:
        get_step_or_404(db, task_id, step_id)
    context_step_ids: set[int] = set()
    if run_id is not None:
        run = db.get(models.StepRun, run_id)
        if run is None or run.task_id != task_id:
            raise HTTPException(status_code=404, detail="Step run not found")
        step_id = step_id or run.step_id
        context_step_ids.add(run.step_id)
    elif step_id is not None:
        context_step_ids.add(step_id)

    entries: list[schemas.TaskLogEntry] = []
    entries.extend(task_context_entries(task, include_sensitive))
    steps = ordered_steps(db, task_id)
    entries.extend(step_log_entry(step, include_sensitive) for step in steps)
    runs = db.query(models.StepRun).filter(models.StepRun.task_id == task_id).order_by(models.StepRun.created_at, models.StepRun.id).all()
    entries.extend(run_log_entry(run, include_sensitive) for run in runs)
    approvals = db.query(models.Approval).filter(models.Approval.task_id == task_id).order_by(models.Approval.created_at, models.Approval.id).all()
    entries.extend(approval_log_entry(approval, include_sensitive) for approval in approvals)
    invocations = list_capability_invocations(db, task_id)
    entries.extend(capability_invocation_log_entry(invocation, include_sensitive) for invocation in invocations)
    artifacts = list_artifacts(db, task_id)
    entries.extend(artifact_log_entry(artifact, include_sensitive) for artifact in artifacts)
    events = list_timeline(db, task_id)
    entries.extend(event_log_entry(event, include_sensitive) for event in events)
    entries = [entry for entry in entries if include_log_entry(entry, step_id, run_id, context_step_ids)]
    entries.sort(key=log_entry_sort_key)
    return render_execution_log_text(task, entries)

def task_log_path(task_id: int) -> str:
    return str(TASK_LOG_DIR / f"task_{task_id}.log")


def task_read_schema(task: models.Task) -> schemas.TaskRead:
    data = schemas.TaskRead.model_validate(task)
    data.log_path = task_log_path(task.id)
    return data


def write_task_execution_log_files(db: Session, task_id: int) -> None:
    log_text = generate_task_execution_log_text(db, task_id, include_sensitive=False)
    text_path = Path(task_log_path(task_id))
    TASK_LOG_DIR.mkdir(parents=True, exist_ok=True)
    text_path.write_text(log_text, encoding="utf-8")
    legacy_json_path = text_path.with_suffix(".json")
    if legacy_json_path.exists():
        legacy_json_path.unlink()


def commit_and_write_task_log(db: Session, task_id: int) -> None:
    db.commit()
    write_task_execution_log_files(db, task_id)


def ensure_executor_type(value: str) -> None:
    if value not in VALID_EXECUTOR_TYPES:
        raise HTTPException(status_code=422, detail="executor_type must be human, agent, worker, system, or codex")


def get_task_or_404(db: Session, task_id: int) -> models.Task:
    task = db.get(models.Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def get_step_or_404(db: Session, task_id: int, step_id: int) -> models.Step:
    step = db.get(models.Step, step_id)
    if step is None or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="Step not found")
    return step


def get_comparison_group_or_404(db: Session, task_id: int, comparison_group_id: int) -> models.StepComparisonGroup:
    group = db.get(models.StepComparisonGroup, comparison_group_id)
    if group is None or group.task_id != task_id:
        raise HTTPException(status_code=404, detail="Step comparison group not found")
    return group


def group_status(group: models.StepComparisonGroup) -> str:
    return group.status or group.selection_status


def list_group_variants(db: Session, group: models.StepComparisonGroup) -> list[models.Step]:
    return (
        db.query(models.Step)
        .filter(models.Step.task_id == group.task_id, models.Step.comparison_group_id == group.id)
        .order_by(models.Step.created_at, models.Step.step_order, models.Step.id)
        .all()
    )


def variant_summary(db: Session, step: models.Step) -> schemas.StepVariantSummary:
    runs = db.query(models.StepRun).filter(models.StepRun.step_id == step.id).all()
    artifacts_count = db.query(func.count(models.Artifact.id)).filter(models.Artifact.step_id == step.id).scalar() or 0
    return schemas.StepVariantSummary(
        step_id=step.id,
        variant_label=step.variant_label,
        status=step.status,
        branch_status=step.branch_status,
        runs_count=len(runs),
        approved_run_id=step.approved_run_id,
        artifacts_count=artifacts_count,
        metrics={
            "failed_runs": sum(1 for run in runs if run.status == "failed"),
            "accepted_runs": sum(1 for run in runs if run.status == "accepted"),
        },
    )


def comparison_group_to_schema(db: Session, group: models.StepComparisonGroup) -> schemas.StepComparisonGroupRead:
    actions: list[schemas.NextAction] = []
    if group_status(group) in {"open", "comparing"}:
        actions.append(
            schemas.NextAction(
                action_type="select_step_variant",
                target_type="comparison_group",
                target={"task_id": group.task_id, "comparison_group_id": group.id},
                label="Select a step variant",
                api=schemas.NextActionApi(method="POST", path=f"/tasks/{group.task_id}/step-comparisons/{group.id}/select"),
                requires_user_input=True,
                input_schema={"selected_step_id": "number", "note": "string"},
            )
        )
    return schemas.StepComparisonGroupRead(
        comparison_group_id=group.id,
        task_id=group.task_id,
        base_step_id=group.base_step_id or group.origin_step_id,
        status=group_status(group),
        selected_step_id=group.selected_step_id,
        resolved_at=group.resolved_at,
        variants=[variant_summary(db, step) for step in list_group_variants(db, group)],
        next_actions=actions,
    )


def ensure_group_selectable(group: models.StepComparisonGroup) -> None:
    if group_status(group) not in {"open", "comparing"}:
        raise HTTPException(status_code=400, detail="Comparison group is not selectable")


def ensure_step_variant_belongs_to_group(step: models.Step, group: models.StepComparisonGroup) -> None:
    if step.task_id != group.task_id or step.comparison_group_id != group.id:
        raise HTTPException(status_code=400, detail="Step is not a variant in this comparison group")


def get_subtree_steps(db: Session, task_id: int, root_step_id: int) -> list[models.Step]:
    descendants: list[models.Step] = []
    pending = [root_step_id]
    while pending:
        parent_id = pending.pop(0)
        children = (
            db.query(models.Step)
            .filter(models.Step.task_id == task_id, models.Step.parent_step_id == parent_id, models.Step.is_active.is_(True), models.Step.status != "superseded")
            .order_by(models.Step.step_order, models.Step.position, models.Step.id)
            .all()
        )
        descendants.extend(children)
        pending.extend(child.id for child in children)
    return descendants


def get_run_or_404(db: Session, task_id: int, step_id: int, run_id: int) -> models.StepRun:
    run = db.get(models.StepRun, run_id)
    if run is None or run.task_id != task_id or run.step_id != step_id:
        raise HTTPException(status_code=404, detail="Step run not found")
    return run


def record_event(
    db: Session,
    task_id: int,
    event_type: str,
    payload: dict[str, Any] | None = None,
    step_id: int | None = None,
    run_id: int | None = None,
    capability_invocation_id: int | None = None,
) -> models.Event:
    event = models.Event(
        task_id=task_id,
        step_id=step_id,
        run_id=run_id,
        capability_invocation_id=capability_invocation_id,
        event_type=event_type,
        payload=encode_json(payload or {}),
    )
    db.add(event)
    return event


def recalculate_progress_event(db: Session, task_id: int, reason: str = "progress_recalculated", previous_progress_percent: float | None = None) -> None:
    progress = compute_progress(db, task_id)
    payload = progress.model_dump()
    if previous_progress_percent is not None:
        payload["previous_progress_percent"] = previous_progress_percent
        payload["new_progress_percent"] = progress.progress_percent
    payload["reason"] = reason
    record_event(db, task_id, "progress_recalculated", payload)


def current_progress_percent(db: Session, task_id: int) -> float:
    return compute_progress(db, task_id).progress_percent


def assert_task_allows_step_mutation(task: models.Task) -> None:
    if task.status == "archived":
        raise HTTPException(status_code=400, detail="Archived tasks do not allow step changes")
    if task.status == "completed":
        raise HTTPException(status_code=400, detail="Completed tasks do not allow new step changes; create a follow-up task")
    if task.status not in STEP_MUTATION_TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"Task status {task.status} does not allow step changes")


def ordered_steps(db: Session, task_id: int, active_only: bool = False) -> list[models.Step]:
    query = db.query(models.Step).filter(models.Step.task_id == task_id)
    if active_only:
        query = query.filter(models.Step.is_active.is_(True), models.Step.status != "superseded")
    return query.order_by(models.Step.step_order, models.Step.position, models.Step.id).all()


def normalized_step_ids(value: Any) -> list[int]:
    if not value:
        return []
    normalized: list[int] = []
    for item in value:
        if not isinstance(item, int) or item in normalized:
            continue
        normalized.append(item)
    return normalized


def set_previous_step_ids(step: models.Step, step_ids: list[int]) -> None:
    step.previous_step_ids = normalized_step_ids(step_ids)


def set_next_step_ids(step: models.Step, step_ids: list[int]) -> None:
    step.next_step_ids = normalized_step_ids(step_ids)


def link_steps(previous: models.Step, next_step: models.Step) -> None:
    if previous.id == next_step.id:
        return
    set_next_step_ids(previous, [*normalized_step_ids(previous.next_step_ids), next_step.id])
    set_previous_step_ids(next_step, [*normalized_step_ids(next_step.previous_step_ids), previous.id])


def unlink_steps(previous: models.Step, next_step: models.Step) -> None:
    set_next_step_ids(previous, [item for item in normalized_step_ids(previous.next_step_ids) if item != next_step.id])
    set_previous_step_ids(next_step, [item for item in normalized_step_ids(next_step.previous_step_ids) if item != previous.id])


def graph_step_by_id(db: Session, task_id: int, step_id: int) -> models.Step | None:
    step = db.get(models.Step, step_id)
    if step is None or step.task_id != task_id or not step.is_active or step.status == "superseded" or step.branch_status in EXCLUDED_BRANCH_STATUSES:
        return None
    return step


def graph_successors(db: Session, task_id: int, step: models.Step) -> list[models.Step]:
    successors: list[models.Step] = []
    for step_id in normalized_step_ids(step.next_step_ids):
        successor = graph_step_by_id(db, task_id, step_id)
        if successor is not None:
            successors.append(successor)
    return successors


def graph_predecessors(db: Session, task_id: int, step: models.Step) -> list[models.Step]:
    predecessors: list[models.Step] = []
    for step_id in normalized_step_ids(step.previous_step_ids):
        predecessor = graph_step_by_id(db, task_id, step_id)
        if predecessor is not None:
            predecessors.append(predecessor)
    return predecessors


def graph_downstream_steps(db: Session, task_id: int, start_step: models.Step) -> list[models.Step]:
    downstream: list[models.Step] = []
    seen = {start_step.id}
    queue = graph_successors(db, task_id, start_step)
    while queue:
        step = queue.pop(0)
        if step.id in seen:
            continue
        seen.add(step.id)
        downstream.append(step)
        queue.extend(graph_successors(db, task_id, step))
    return downstream


def graph_continuation_steps(db: Session, task_id: int, start_step: models.Step) -> list[models.Step]:
    downstream: list[models.Step] = []
    seen = {start_step.id}
    queue: list[tuple[models.Step, models.Step]] = [(start_step, successor) for successor in graph_successors(db, task_id, start_step)]
    while queue:
        previous, step = queue.pop(0)
        if step.id in seen:
            continue
        if step.is_fork and step.cloned_from_step_id is None and step.forked_from_step_id == previous.id:
            continue
        seen.add(step.id)
        downstream.append(step)
        queue.extend((step, successor) for successor in graph_successors(db, task_id, step))
    return downstream


def ensure_step_graph_backfilled(db: Session, task_id: int) -> None:
    steps = ordered_steps(db, task_id, active_only=True)
    if not steps:
        return
    graph_step_ids = {step.id for step in steps}
    steps_by_id = {step.id: step for step in steps}
    for step in steps:
        set_previous_step_ids(step, [step_id for step_id in normalized_step_ids(step.previous_step_ids) if step_id in graph_step_ids])
        set_next_step_ids(step, [step_id for step_id in normalized_step_ids(step.next_step_ids) if step_id in graph_step_ids])
    for step in steps:
        for previous_step_id in normalized_step_ids(step.previous_step_ids):
            previous = steps_by_id.get(previous_step_id)
            if previous is not None:
                link_steps(previous, step)
        for next_step_id in normalized_step_ids(step.next_step_ids):
            next_step = steps_by_id.get(next_step_id)
            if next_step is not None:
                link_steps(step, next_step)
    branch_roots = [step for step in steps if step.is_fork and step.cloned_from_step_id is None and step.forked_from_step_id]
    for root in branch_roots:
        source = db.get(models.Step, root.forked_from_step_id)
        if source is not None and source.task_id == task_id:
            unlink_steps(source, root)
    if any(normalized_step_ids(step.previous_step_ids) or normalized_step_ids(step.next_step_ids) for step in steps):
        return
    main_steps = [step for step in steps if not step.is_fork and step.cloned_from_step_id is None]
    for previous, next_step in zip(main_steps, main_steps[1:]):
        link_steps(previous, next_step)
    branch_batches: dict[str, list[models.Step]] = {}
    for step in steps:
        if step.clone_batch_id:
            branch_batches.setdefault(step.clone_batch_id, []).append(step)
    for branch_steps in branch_batches.values():
        branch_steps.sort(key=lambda item: (item.step_order, item.position, item.id))
        roots = [step for step in branch_steps if step.cloned_from_step_id is None] or [branch_steps[0]]
        for root in roots:
            source = db.get(models.Step, root.forked_from_step_id) if root.forked_from_step_id else None
            if source is not None and source.task_id == task_id:
                source_downstream_ids = {item.id for item in graph_continuation_steps(db, task_id, source)}
                clones = [step for step in branch_steps if step.cloned_from_step_id in source_downstream_ids]
            else:
                clones = [step for step in branch_steps if step.id != root.id]
            previous = root
            for clone in sorted(clones, key=lambda item: (item.step_order, item.position, item.id)):
                link_steps(previous, clone)
                previous = clone


def normalize_step_order(db: Session, task_id: int) -> None:
    for index, step in enumerate(ordered_steps(db, task_id, active_only=True), start=1):
        step.step_order = index
        step.position = index


def next_step_order(db: Session, task_id: int) -> int:
    max_order = db.query(func.max(models.Step.step_order)).filter(models.Step.task_id == task_id, models.Step.is_active.is_(True)).scalar()
    max_position = db.query(func.max(models.Step.position)).filter(models.Step.task_id == task_id, models.Step.is_active.is_(True)).scalar()
    return max(max_order or 0, max_position or 0) + 1


def validate_dependency_ids(db: Session, task_id: int, depends_on_step_ids: list[int], step_id: int | None = None) -> list[int]:
    normalized: list[int] = []
    for dependency_id in depends_on_step_ids:
        if dependency_id in normalized:
            continue
        if step_id is not None and dependency_id == step_id:
            raise HTTPException(status_code=400, detail="Step cannot depend on itself")
        dependency = get_step_or_404(db, task_id, dependency_id)
        if not dependency.is_active or dependency.status == "superseded":
            raise HTTPException(status_code=400, detail="Step cannot depend on inactive or superseded steps")
        normalized.append(dependency_id)
    return normalized


def dependencies_satisfied(db: Session, step: models.Step) -> bool:
    for dependency_id in step.depends_on_step_ids or []:
        dependency = db.get(models.Step, dependency_id)
        if dependency is None or dependency.task_id != step.task_id or dependency.status not in COMPLETED_STEP_STATUSES:
            return False
    return True


def graph_ordered_steps(db: Session, task_id: int, active_only: bool = False) -> list[models.Step]:
    steps = ordered_steps(db, task_id, active_only=active_only)
    if not steps:
        return []
    by_id = {step.id: step for step in steps}
    roots = [step for step in steps if not any(previous_id in by_id for previous_id in normalized_step_ids(step.previous_step_ids))]
    roots.sort(key=lambda item: (item.step_order, item.position, item.id))
    ordered: list[models.Step] = []
    seen: set[int] = set()

    def visit(step: models.Step) -> None:
        if step.id in seen:
            return
        seen.add(step.id)
        ordered.append(step)
        successors = [by_id[step_id] for step_id in normalized_step_ids(step.next_step_ids) if step_id in by_id]
        successors.sort(key=lambda item: (item.step_order, item.position, item.id))
        for successor in successors:
            visit(successor)

    for root in roots:
        visit(root)
    for step in steps:
        visit(step)
    return ordered


def previous_graph_steps(db: Session, task_id: int, step: models.Step) -> list[models.Step]:
    steps = graph_ordered_steps(db, task_id, active_only=True)
    if not normalized_step_ids(step.previous_step_ids):
        return [item for item in steps if item.step_order < step.step_order]
    target_index = next((index for index, item in enumerate(steps) if item.id == step.id), None)
    return steps[:target_index] if target_index is not None else []


def next_startable_step(db: Session, task_id: int) -> models.Step | None:
    ensure_step_graph_backfilled(db, task_id)
    return next_startable_ordered_step(db, graph_ordered_steps(db, task_id, active_only=True))


def ensure_step_attempt_limit(db: Session, step: models.Step) -> None:
    if step.max_attempts is not None:
        attempts = db.query(func.count(models.StepRun.id)).filter(models.StepRun.step_id == step.id).scalar() or 0
        if attempts >= step.max_attempts:
            raise HTTPException(status_code=400, detail="Step has reached max_attempts")


def ensure_step_can_run(db: Session, step: models.Step) -> None:
    task = db.get(models.Task, step.task_id)
    if task and task.status in {"intake", "planning", "waiting_plan_review"}:
        raise HTTPException(status_code=400, detail="Plan must be approved before steps can run")
    if not step.is_active or step.status == "superseded":
        raise HTTPException(status_code=400, detail="Inactive or superseded steps cannot be run")
    if step.branch_status in EXCLUDED_BRANCH_STATUSES:
        raise HTTPException(status_code=400, detail="Inactive step variants cannot be run")
    if step.status not in STARTABLE_STEP_STATUSES:
        raise HTTPException(status_code=400, detail=f"Step status {step.status} cannot start a run")
    if not dependencies_satisfied(db, step):
        raise HTTPException(status_code=400, detail="Step dependencies are not satisfied")
    next_step = next_startable_step(db, step.task_id)
    if next_step is None:
        raise HTTPException(status_code=400, detail="Only the next pending step can start a run")
    if next_step.id != step.id:
        if step.comparison_group_id is None:
            raise HTTPException(status_code=400, detail="Only the next pending step can start a run")
        if has_running_or_review_step(db, step.task_id):
            raise HTTPException(status_code=400, detail="Only the next pending step can start a run")
    ensure_step_attempt_limit(db, step)


def has_running_or_review_step(db: Session, task_id: int, exclude_step_id: int | None = None) -> bool:
    query = db.query(models.Step).filter(
        models.Step.task_id == task_id,
        models.Step.status.in_(["running", "waiting_review"]),
    )
    if exclude_step_id is not None:
        query = query.filter(models.Step.id != exclude_step_id)
    return db.query(query.exists()).scalar()


def latest_step_run_id(db: Session, step_id: int) -> int | None:
    return db.query(models.StepRun.id).filter(models.StepRun.step_id == step_id).order_by(models.StepRun.attempt_number.desc(), models.StepRun.id.desc()).scalar()


def ensure_step_can_rerun(db: Session, step: models.Step) -> None:
    if not step.is_active or step.status == "superseded":
        raise HTTPException(status_code=400, detail="Inactive or superseded steps cannot be rerun")
    if step.branch_status in EXCLUDED_BRANCH_STATUSES:
        raise HTTPException(status_code=400, detail="Inactive step variants cannot be rerun")
    if step.status not in RERUNNABLE_STEP_STATUSES:
        raise HTTPException(status_code=400, detail=f"Step status {step.status} cannot be rerun")
    if not dependencies_satisfied(db, step):
        raise HTTPException(status_code=400, detail="Step dependencies are not satisfied")
    if has_running_or_review_step(db, step.task_id):
        raise HTTPException(status_code=400, detail="Cannot create a rerun branch while another step is running or waiting for review")


def update_task_completion_status(db: Session, task: models.Task) -> None:
    if task.status in {"archived", "cancelled", "failed"}:
        return
    active_steps = progress_eligible_steps(db, task.id)
    if active_steps and all(step.status in COMPLETED_STEP_STATUSES for step in active_steps):
        task.status = "completed"
    elif any(step.status == "running" for step in active_steps):
        task.status = "running"
    elif any(step.status == "waiting_review" for step in active_steps):
        task.status = "waiting_review"
    elif any(step.status == "needs_revision" for step in active_steps):
        task.status = "needs_revision"
    elif active_steps and any(step.status in STARTABLE_STEP_STATUSES for step in active_steps):
        task.status = "planned"


def capability_invocation_summary(invocation: models.CapabilityInvocation) -> schemas.CapabilityInvocationSummary:
    return schemas.CapabilityInvocationSummary(
        id=invocation.id,
        step_id=invocation.step_id,
        run_id=invocation.run_id,
        capability_id=invocation.capability_id,
        capability_name=invocation.capability_name,
        status=invocation.status,
        created_at=invocation.created_at,
        completed_at=invocation.completed_at,
    )


def set_run_duration(run: models.StepRun, ended_at) -> None:
    if run.duration_ms is None:
        run.duration_ms = run_consumed_ms(run, ended_at)


def step_to_schema(step: models.Step, consumed_ms: int = 0) -> schemas.StepRead:
    data = schemas.StepRead.model_validate(step).model_dump()
    data["consumed_ms"] = consumed_ms
    return schemas.StepRead(**data)


def step_consumed_totals(runs: list[models.StepRun], now) -> dict[int, int]:
    totals: dict[int, int] = {}
    for run in runs:
        totals[run.step_id] = totals.get(run.step_id, 0) + run_consumed_ms(run, now)
    return totals


def steps_to_schema(db: Session, task_id: int, steps: list[models.Step]) -> list[schemas.StepRead]:
    runs = db.query(models.StepRun).filter(models.StepRun.task_id == task_id).all()
    consumed_by_step = step_consumed_totals(runs, models.utcnow())
    return [step_to_schema(step, consumed_by_step.get(step.id, 0)) for step in steps]


def ensure_codex_project_path(project_path: str | None) -> str:
    path = Path(project_path or "").expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise HTTPException(status_code=422, detail="project_path must be a directory when executor_mode is codex")
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def create_task(db: Session, payload: schemas.TaskCreate) -> models.Task:
    project_path = payload.project_path
    if payload.executor_mode == "codex":
        if not settings.codex_enabled:
            raise HTTPException(status_code=503, detail="Codex executor is not enabled")
        if not settings.codex_callback_secret:
            raise HTTPException(status_code=503, detail="Codex callback secret is not configured")
        project_path = ensure_codex_project_path(payload.project_path)
    task = models.Task(
        title=payload.title,
        goal=payload.goal,
        constraints=payload.constraints,
        status="intake",
        created_by=payload.created_by,
        executor_mode=payload.executor_mode,
        project_path=project_path,
    )
    db.add(task)
    db.flush()
    record_event(db, task.id, "task_created", {"title": task.title})

    if payload.initial_message:
        message = models.TaskMessage(
            task_id=task.id,
            author_type="human",
            message=payload.initial_message,
            constraints=payload.constraints,
        )
        db.add(message)
        db.flush()
        record_event(db, task.id, "task_message_added", {"message_id": message.id})

    recalculate_progress_event(db, task.id, "task_created")
    commit_and_write_task_log(db, task.id)
    db.refresh(task)
    return task


def close_task(db: Session, task_id: int, payload: schemas.TaskCloseRequest, kill_tmux_session) -> schemas.TaskDetailResponse:
    task = get_task_or_404(db, task_id)
    if task.status == "cancelled":
        return get_task_detail(db, task_id)

    previous = current_progress_percent(db, task_id)
    previous_status = task.status
    task.status = "cancelled"
    reason = payload.reason or "Task closed"
    running_runs = db.query(models.StepRun).filter(models.StepRun.task_id == task_id, models.StepRun.status == "running").all()
    cancelled_run_ids = []
    for run in running_runs:
        run.status = "cancelled"
        run.error = reason
        run.ended_at = models.utcnow()
        set_run_duration(run, run.ended_at)
        cancelled_run_ids.append(run.id)

    tmux_session = task.codex_tmux_session
    if task.executor_mode == "codex" and not tmux_session:
        tmux_session = f"longagent-t{task.id}"
    killed_tmux = False
    if tmux_session:
        kill_tmux_session(tmux_session)
        killed_tmux = True

    record_event(
        db,
        task_id,
        "task_closed",
        {
            "reason": payload.reason,
            "actor_id": payload.actor_id,
            "previous_status": previous_status,
            "tmux_session": tmux_session,
            "killed_tmux": killed_tmux,
            "cancelled_run_ids": cancelled_run_ids,
        },
    )
    recalculate_progress_event(db, task_id, "task_closed", previous)
    commit_and_write_task_log(db, task_id)
    return get_task_detail(db, task_id)


def list_tasks(db: Session) -> list[models.Task]:
    return db.query(models.Task).order_by(models.Task.created_at.desc(), models.Task.id.desc()).all()


def backfill_all_step_graphs(db: Session) -> None:
    task_ids = [task_id for (task_id,) in db.query(models.Step.task_id).distinct().all()]
    for task_id in task_ids:
        ensure_step_graph_backfilled(db, task_id)
    db.commit()


def get_task_detail(db: Session, task_id: int) -> schemas.TaskDetailResponse:
    task = get_task_or_404(db, task_id)
    ensure_step_graph_backfilled(db, task_id)
    steps = ordered_steps(db, task_id)
    invocations = list_capability_invocations(db, task_id)
    return schemas.TaskDetailResponse(
        task=task_read_schema(task),
        steps=steps_to_schema(db, task_id, steps),
        progress=compute_progress(db, task_id),
        current_pointer=build_current_pointer(db, task_id),
        next_actions=build_next_actions(db, task_id),
        capability_invocations_count=len(invocations),
        latest_capability_invocations=[capability_invocation_summary(invocation) for invocation in invocations[-5:]],
    )


def add_message(db: Session, task_id: int, payload: schemas.TaskMessageCreate) -> models.TaskMessage:
    task = get_task_or_404(db, task_id)
    ensure_executor_type(payload.author_type)
    message = models.TaskMessage(
        task_id=task_id,
        author_type=payload.author_type,
        author_id=payload.author_id,
        message=payload.message,
        constraints=payload.constraints,
    )
    db.add(message)
    db.flush()
    if payload.constraints:
        task.constraints = payload.constraints
    record_event(db, task_id, "task_message_added", {"message_id": message.id})
    commit_and_write_task_log(db, task_id)
    db.refresh(message)
    return message


def list_messages(db: Session, task_id: int) -> list[models.TaskMessage]:
    get_task_or_404(db, task_id)
    return db.query(models.TaskMessage).filter(models.TaskMessage.task_id == task_id).order_by(models.TaskMessage.created_at, models.TaskMessage.id).all()


def create_revision(db: Session, task: models.Task, reason: str) -> models.TaskRevision:
    max_revision = db.query(func.max(models.TaskRevision.revision_number)).filter(models.TaskRevision.task_id == task.id).scalar()
    revision = models.TaskRevision(task_id=task.id, revision_number=(max_revision or 0) + 1, reason=reason)
    db.add(revision)
    db.flush()
    task.current_revision_id = revision.id
    record_event(db, task.id, "task_revision_created", {"revision_id": revision.id, "reason": reason})
    return revision


def create_step_record(
    db: Session,
    task_id: int,
    payload: schemas.StepCreate | schemas.PlanStepCreate | schemas.SupersedeStepCreate,
    *,
    is_dynamic: bool,
    step_order: int | None = None,
    inserted_after_step_id: int | None = None,
    supersedes_step_id: int | None = None,
    created_reason: str | None = None,
    created_by_type: str = "system",
    created_by_id: str | None = None,
    depends_on_step_ids: list[int] | None = None,
    event_type: str = "step_added",
) -> models.Step:
    parent_step_id = getattr(payload, "parent_step_id", None)
    if parent_step_id is not None:
        get_step_or_404(db, task_id, parent_step_id)
    order = step_order if step_order is not None else next_step_order(db, task_id)
    step = models.Step(
        task_id=task_id,
        parent_step_id=parent_step_id,
        title=payload.title,
        objective=payload.objective,
        status="pending",
        position=order,
        step_order=order,
        depends_on_step_ids=depends_on_step_ids if depends_on_step_ids is not None else validate_dependency_ids(db, task_id, getattr(payload, "depends_on_step_ids", [])),
        is_active=True,
        is_dynamic=is_dynamic,
        created_reason=created_reason if created_reason is not None else getattr(payload, "created_reason", None),
        created_by_type=created_by_type,
        created_by_id=created_by_id,
        inserted_after_step_id=inserted_after_step_id,
        supersedes_step_id=supersedes_step_id,
        executor_hint=getattr(payload, "executor_hint", None),
        requires_approval=getattr(payload, "requires_approval", True),
        max_attempts=getattr(payload, "max_attempts", None),
    )
    db.add(step)
    db.flush()
    record_event(db, task_id, event_type, {"step_id": step.id, "title": step.title, "step_order": step.step_order}, step_id=step.id)
    return step


def generate_plan(db: Session, task_id: int, payload: schemas.GeneratePlanRequest) -> schemas.TaskDetailResponse:
    task = get_task_or_404(db, task_id)
    if task.status not in {"intake", "needs_revision", "waiting_plan_review"}:
        raise HTTPException(status_code=400, detail="Task status does not allow plan generation")
    existing_steps = ordered_steps(db, task_id)
    if existing_steps:
        if task.status != "waiting_plan_review":
            raise HTTPException(status_code=400, detail="Task already has steps")
        existing_runs = db.query(func.count(models.StepRun.id)).filter(models.StepRun.task_id == task_id).scalar() or 0
        if existing_runs:
            raise HTTPException(status_code=400, detail="Cannot replace a plan after step runs exist")
        for step in existing_steps:
            db.delete(step)
        db.flush()

    steps = payload.steps or []
    if payload.generation_mode == "auto":
        messages = list_messages(db, task_id)
        system_prompt = settings_service.require_planner_prompt(db)
        record_event(db, task_id, "llm_call", plan_llm_call_payload(task, messages, system_prompt, payload.instructions))
        steps = generate_plan_steps(task, messages, system_prompt, payload.instructions)
    if not steps:
        raise HTTPException(status_code=400, detail="Plan generation requires at least one step")

    revision = create_revision(db, task, payload.reason)
    previous_step = None
    for step_payload in steps:
        step = create_step_record(db, task_id, step_payload, is_dynamic=False, created_reason=payload.reason, event_type="step_added")
        if previous_step is not None:
            link_steps(previous_step, step)
        previous_step = step
    normalize_step_order(db, task_id)
    task.status = "waiting_plan_review"
    record_event(
        db,
        task_id,
        "task_plan_generated",
        {"revision_id": revision.id, "step_count": len(steps), "generation_mode": payload.generation_mode},
    )
    recalculate_progress_event(db, task_id, "task_plan_generated")
    commit_and_write_task_log(db, task_id)
    return get_task_detail(db, task_id)


def approve_plan(db: Session, task_id: int, payload: schemas.ApprovePlanRequest) -> schemas.TaskDetailResponse:
    task = get_task_or_404(db, task_id)
    ensure_executor_type(payload.reviewed_by_type)
    if task.status != "waiting_plan_review":
        raise HTTPException(status_code=400, detail="Task is not waiting for plan review")
    if not ordered_steps(db, task_id, active_only=True):
        raise HTTPException(status_code=400, detail="Cannot approve a plan with no steps")
    if payload.decision == "approved":
        task.status = "planned"
        record_event(db, task_id, "task_plan_approved", {"decision": payload.decision, "comment": payload.comment})
    else:
        task.status = "needs_revision"
        record_event(db, task_id, "task_plan_approved", {"decision": payload.decision, "comment": payload.comment})
    commit_and_write_task_log(db, task_id)
    return get_task_detail(db, task_id)


def create_step(db: Session, task_id: int, payload: schemas.StepCreate) -> models.Step:
    task = get_task_or_404(db, task_id)
    assert_task_allows_step_mutation(task)
    previous = current_progress_percent(db, task_id)
    if payload.insert_mode in {"insert_after_current", "insert_before_next"}:
        raise HTTPException(status_code=400, detail=f"insert_mode {payload.insert_mode} is reserved for a later phase")

    target = get_step_or_404(db, task_id, payload.target_step_id) if payload.target_step_id is not None else None
    event_type = "step_added"
    inserted_after_step_id = None
    if payload.insert_mode == "append_to_end":
        order = next_step_order(db, task_id)
    elif payload.insert_mode == "insert_after_step":
        if target is None:
            raise HTTPException(status_code=400, detail="target_step_id is required for insert_after_step")
        if not target.is_active:
            raise HTTPException(status_code=400, detail="Cannot insert relative to inactive step")
        order = target.step_order + 1
        inserted_after_step_id = target.id
        event_type = "step_inserted"
        for step in ordered_steps(db, task_id, active_only=True):
            if step.step_order >= order:
                step.step_order += 1
                step.position += 1
    elif payload.insert_mode == "insert_before_step":
        if target is None:
            raise HTTPException(status_code=400, detail="target_step_id is required for insert_before_step")
        if not target.is_active:
            raise HTTPException(status_code=400, detail="Cannot insert relative to inactive step")
        order = target.step_order
        event_type = "step_inserted"
        for step in ordered_steps(db, task_id, active_only=True):
            if step.step_order >= order:
                step.step_order += 1
                step.position += 1
    else:
        raise HTTPException(status_code=400, detail="Unsupported insert_mode")

    ensure_step_graph_backfilled(db, task_id)
    previous_neighbors: list[models.Step] = []
    next_neighbors: list[models.Step] = []
    if payload.insert_mode == "append_to_end":
        active_steps = ordered_steps(db, task_id, active_only=True)
        previous_neighbors = [step for step in active_steps if not normalized_step_ids(step.next_step_ids)]
    elif payload.insert_mode == "insert_after_step" and target is not None:
        previous_neighbors = [target]
        next_neighbors = graph_successors(db, task_id, target)
    elif payload.insert_mode == "insert_before_step" and target is not None:
        previous_neighbors = graph_predecessors(db, task_id, target)
        next_neighbors = [target]

    step = create_step_record(
        db,
        task_id,
        payload,
        is_dynamic=True,
        step_order=order,
        inserted_after_step_id=inserted_after_step_id,
        created_reason=payload.created_reason,
        created_by_type=payload.created_by_type,
        created_by_id=payload.created_by_id,
        depends_on_step_ids=validate_dependency_ids(db, task_id, payload.depends_on_step_ids),
        event_type=event_type,
    )
    for previous_step in previous_neighbors:
        for next_step in next_neighbors:
            unlink_steps(previous_step, next_step)
        link_steps(previous_step, step)
    for next_step in next_neighbors:
        link_steps(step, next_step)
    normalize_step_order(db, task_id)
    recalculate_progress_event(db, task_id, event_type, previous)
    commit_and_write_task_log(db, task_id)
    db.refresh(step)
    return step


def update_step(db: Session, task_id: int, step_id: int, payload: schemas.StepPatchRequest) -> models.Step:
    task = get_task_or_404(db, task_id)
    if task.status == "archived":
        raise HTTPException(status_code=400, detail="Archived tasks do not allow step changes")
    step = get_step_or_404(db, task_id, step_id)
    content_change_requested = any(value is not None for value in [payload.title, payload.objective, payload.depends_on_step_ids])
    has_run_history = db.query(models.StepRun.id).filter(models.StepRun.task_id == task_id, models.StepRun.step_id == step.id).first() is not None
    if content_change_requested and has_run_history:
        raise HTTPException(status_code=400, detail="Steps with run history cannot be directly modified")
    previous = current_progress_percent(db, task_id)
    old_order = step.step_order

    if payload.title is not None:
        step.title = payload.title
    if payload.objective is not None:
        step.objective = payload.objective
    if payload.depends_on_step_ids is not None:
        step.depends_on_step_ids = validate_dependency_ids(db, task_id, payload.depends_on_step_ids, step_id=step.id)
    if payload.executor_hint is not None:
        step.executor_hint = payload.executor_hint
    if payload.requires_approval is not None:
        step.requires_approval = payload.requires_approval
    if payload.max_attempts is not None:
        step.max_attempts = payload.max_attempts

    record_event(db, task_id, "step_updated", {"step_id": step.id}, step_id=step.id)
    if payload.step_order is not None and payload.step_order != old_order:
        active = [item for item in ordered_steps(db, task_id, active_only=True) if item.id != step.id]
        new_order = max(1, min(payload.step_order, len(active) + 1))
        active.insert(new_order - 1, step)
        for index, item in enumerate(active, start=1):
            item.step_order = index
            item.position = index
        record_event(db, task_id, "step_reordered", {"step_id": step.id, "previous_step_order": old_order, "new_step_order": new_order}, step_id=step.id)
    else:
        normalize_step_order(db, task_id)

    recalculate_progress_event(db, task_id, "step_updated", previous)
    commit_and_write_task_log(db, task_id)
    db.refresh(step)
    return step


def list_steps(db: Session, task_id: int) -> list[models.Step]:
    get_task_or_404(db, task_id)
    ensure_step_graph_backfilled(db, task_id)
    return ordered_steps(db, task_id)


def skip_step(db: Session, task_id: int, step_id: int, payload: schemas.StepSkipRequest) -> models.Step:
    task = get_task_or_404(db, task_id)
    if task.status == "archived":
        raise HTTPException(status_code=400, detail="Archived tasks do not allow step changes")
    step = get_step_or_404(db, task_id, step_id)
    if step.status not in {"pending", "needs_revision", "failed"}:
        raise HTTPException(status_code=400, detail="Only pending, needs_revision, or failed steps can be skipped")
    previous = current_progress_percent(db, task_id)
    step.status = "skipped"
    record_event(db, task_id, "step_skipped", {"step_id": step.id, "reason": payload.reason, "actor_id": payload.actor_id}, step_id=step.id)
    update_task_completion_status(db, task)
    recalculate_progress_event(db, task_id, "step_skipped", previous)
    commit_and_write_task_log(db, task_id)
    db.refresh(step)
    return step


def supersede_step(db: Session, task_id: int, step_id: int, payload: schemas.StepSupersedeRequest) -> models.Step:
    task = get_task_or_404(db, task_id)
    assert_task_allows_step_mutation(task)
    old_step = get_step_or_404(db, task_id, step_id)
    if not old_step.is_active or old_step.status == "superseded":
        raise HTTPException(status_code=400, detail="Only active steps can be superseded")
    if old_step.status in {"running", "waiting_review"}:
        raise HTTPException(status_code=400, detail="Running or waiting_review steps cannot be superseded")
    previous = current_progress_percent(db, task_id)
    ensure_step_graph_backfilled(db, task_id)
    previous_neighbors = graph_predecessors(db, task_id, old_step)
    next_neighbors = graph_successors(db, task_id, old_step)
    order = old_step.step_order
    dependencies = payload.new_step.depends_on_step_ids if payload.new_step.depends_on_step_ids is not None else list(old_step.depends_on_step_ids or [])
    dependencies = validate_dependency_ids(db, task_id, dependencies)

    old_step.status = "superseded"
    old_step.is_active = False
    replacement = create_step_record(
        db,
        task_id,
        payload.new_step,
        is_dynamic=True,
        step_order=order,
        supersedes_step_id=old_step.id,
        created_reason=payload.reason,
        created_by_type="human",
        created_by_id=payload.actor_id,
        depends_on_step_ids=dependencies,
        event_type="step_added",
    )
    db.flush()
    old_step.superseded_by_step_id = replacement.id
    for previous_step in previous_neighbors:
        unlink_steps(previous_step, old_step)
        link_steps(previous_step, replacement)
    for next_step in next_neighbors:
        unlink_steps(old_step, next_step)
        link_steps(replacement, next_step)
    set_previous_step_ids(old_step, [])
    set_next_step_ids(old_step, [])
    for downstream in ordered_steps(db, task_id, active_only=True):
        if downstream.id == replacement.id:
            continue
        downstream.depends_on_step_ids = [replacement.id if item == old_step.id else item for item in downstream.depends_on_step_ids or []]
    record_event(
        db,
        task_id,
        "step_superseded",
        {"old_step_id": old_step.id, "new_step_id": replacement.id, "reason": payload.reason, "actor_id": payload.actor_id},
        step_id=old_step.id,
    )
    normalize_step_order(db, task_id)
    recalculate_progress_event(db, task_id, "step_superseded", previous)
    commit_and_write_task_log(db, task_id)
    db.refresh(replacement)
    return replacement


def clone_step_subtree(db: Session, task_id: int, source_root: models.Step, forked_root: models.Step) -> int:
    source_steps = get_subtree_steps(db, task_id, source_root.id)
    if not source_steps:
        return 0
    clone_batch_id = forked_root.clone_batch_id or str(uuid.uuid4())
    forked_root.clone_batch_id = clone_batch_id
    id_map = {source_root.id: forked_root.id}
    cloned_count = 0
    for source in source_steps:
        clone = models.Step(
            task_id=task_id,
            parent_step_id=id_map.get(source.parent_step_id),
            comparison_group_id=forked_root.comparison_group_id,
            title=source.title,
            objective=source.objective,
            status="pending",
            position=next_step_order(db, task_id),
            step_order=next_step_order(db, task_id),
            depends_on_step_ids=[id_map.get(item, item) for item in source.depends_on_step_ids or []],
            is_active=True,
            is_dynamic=True,
            created_reason=forked_root.fork_reason,
            created_by_type=forked_root.created_by_type,
            created_by_id=forked_root.created_by_id,
            executor_hint=source.executor_hint,
            requires_approval=source.requires_approval,
            max_attempts=source.max_attempts,
            variant_label=forked_root.variant_label,
            is_fork=True,
            forked_from_step_id=source.id,
            forked_from_run_id=forked_root.forked_from_run_id,
            fork_reason=forked_root.fork_reason,
            branch_status="active",
            cloned_from_step_id=source.id,
            clone_batch_id=clone_batch_id,
        )
        db.add(clone)
        db.flush()
        id_map[source.id] = clone.id
        for previous_source_id in normalized_step_ids(source.previous_step_ids):
            previous_clone_id = id_map.get(previous_source_id)
            if previous_clone_id is not None:
                previous_clone = db.get(models.Step, previous_clone_id)
                if previous_clone is not None:
                    link_steps(previous_clone, clone)
        cloned_count += 1
    record_event(db, task_id, "step_subtree_cloned", {"source_step_id": source_root.id, "forked_step_id": forked_root.id, "cloned_steps_count": cloned_count, "clone_batch_id": clone_batch_id}, step_id=forked_root.id)
    return cloned_count


def clone_downstream_steps_for_branch(db: Session, task_id: int, source_step: models.Step, forked_root: models.Step) -> int:
    ensure_step_graph_backfilled(db, task_id)
    source_steps = graph_continuation_steps(db, task_id, source_step)
    if not source_steps:
        return 0
    clone_batch_id = forked_root.clone_batch_id or str(uuid.uuid4())
    forked_root.clone_batch_id = clone_batch_id
    id_map = {source_step.id: forked_root.id}
    cloned_step_ids = []
    for source in source_steps:
        clone = models.Step(
            task_id=task_id,
            parent_step_id=id_map.get(source.parent_step_id, source.parent_step_id),
            comparison_group_id=forked_root.comparison_group_id,
            title=source.title,
            objective=source.objective,
            status="pending",
            position=next_step_order(db, task_id),
            step_order=next_step_order(db, task_id),
            depends_on_step_ids=[id_map.get(item, item) for item in source.depends_on_step_ids or []],
            is_active=True,
            is_dynamic=True,
            created_reason=forked_root.fork_reason,
            created_by_type=forked_root.created_by_type,
            created_by_id=forked_root.created_by_id,
            executor_hint=source.executor_hint,
            requires_approval=source.requires_approval,
            max_attempts=source.max_attempts,
            variant_label=forked_root.variant_label,
            is_fork=True,
            forked_from_step_id=source.id,
            forked_from_run_id=forked_root.forked_from_run_id,
            fork_reason=forked_root.fork_reason,
            branch_status="active",
            cloned_from_step_id=source.id,
            clone_batch_id=clone_batch_id,
        )
        db.add(clone)
        db.flush()
        id_map[source.id] = clone.id
        for previous_source_id in normalized_step_ids(source.previous_step_ids):
            previous_clone_id = id_map.get(previous_source_id)
            if previous_clone_id is not None:
                previous_clone = db.get(models.Step, previous_clone_id)
                if previous_clone is not None:
                    link_steps(previous_clone, clone)
        cloned_step_ids.append(clone.id)
    record_event(
        db,
        task_id,
        "step_branch_cloned",
        {
            "source_step_id": source_step.id,
            "forked_step_id": forked_root.id,
            "clone_batch_id": clone_batch_id,
            "cloned_steps_count": len(cloned_step_ids),
            "cloned_step_ids": cloned_step_ids,
        },
        step_id=forked_root.id,
    )
    return len(cloned_step_ids)


def create_forked_step_without_commit(
    db: Session,
    task_id: int,
    source: models.Step,
    payload: schemas.StepForkRequest,
    clone_batch_id: str | None = None,
    create_comparison_group: bool = True,
) -> tuple[models.StepComparisonGroup | None, models.Step]:
    group = None
    if create_comparison_group:
        if source.comparison_group_id is not None:
            group = get_comparison_group_or_404(db, task_id, source.comparison_group_id)
        if group is None:
            group = models.StepComparisonGroup(
                task_id=task_id,
                origin_step_id=source.id,
                base_step_id=source.id,
                title=f"Variants for {source.title}",
                description=payload.fork_reason,
                selection_status="open",
                status="open",
                created_reason=payload.fork_reason,
                created_by_type=payload.created_by_type,
                created_by_id=payload.created_by_id,
            )
            db.add(group)
            db.flush()
            source.comparison_group_id = group.id
            source.branch_status = "active"
            source.variant_label = source.variant_label or "original"
            record_event(db, task_id, "comparison_group_created", {"comparison_group_id": group.id, "base_step_id": source.id}, step_id=source.id)

    order = source.step_order + 1
    for step in ordered_steps(db, task_id, active_only=True):
        if step.step_order >= order:
            step.step_order += 1
            step.position += 1
    forked = models.Step(
        task_id=task_id,
        parent_step_id=source.parent_step_id,
        comparison_group_id=group.id if group else None,
        title=payload.title,
        objective=payload.objective,
        status="pending",
        position=order,
        step_order=order,
        depends_on_step_ids=list(source.depends_on_step_ids or []),
        is_active=True,
        is_dynamic=True,
        created_reason=payload.fork_reason,
        created_by_type=payload.created_by_type,
        created_by_id=payload.created_by_id,
        executor_hint=source.executor_hint,
        requires_approval=source.requires_approval,
        max_attempts=source.max_attempts,
        variant_label=payload.variant_label,
        is_fork=True,
        forked_from_step_id=source.id,
        forked_from_run_id=payload.forked_from_run_id,
        fork_reason=payload.fork_reason,
        branch_status="active",
        clone_batch_id=clone_batch_id,
    )
    db.add(forked)
    db.flush()
    record_event(db, task_id, "step_forked", {"source_step_id": source.id, "forked_step_id": forked.id, "comparison_group_id": group.id if group else None}, step_id=forked.id)
    return group, forked


def fork_step(db: Session, task_id: int, step_id: int, payload: schemas.StepForkRequest) -> schemas.StepForkResponse:
    task = get_task_or_404(db, task_id)
    assert_task_allows_step_mutation(task)
    ensure_executor_type(payload.created_by_type)
    source = get_step_or_404(db, task_id, step_id)
    if not source.is_active or source.status == "superseded":
        raise HTTPException(status_code=400, detail="Only active steps can be forked")
    previous = current_progress_percent(db, task_id)
    group, forked = create_forked_step_without_commit(db, task_id, source, payload)
    cloned_count = clone_step_subtree(db, task_id, source, forked) if payload.clone_subtree else 0
    normalize_step_order(db, task_id)
    recalculate_progress_event(db, task_id, "step_forked", previous)
    commit_and_write_task_log(db, task_id)
    return schemas.StepForkResponse(comparison_group_id=group.id, forked_step_id=forked.id, cloned_steps_count=cloned_count)


def get_step_comparison(db: Session, task_id: int, comparison_group_id: int) -> schemas.StepComparisonGroupRead:
    group = get_comparison_group_or_404(db, task_id, comparison_group_id)
    return comparison_group_to_schema(db, group)


def select_step_variant(db: Session, task_id: int, comparison_group_id: int, payload: schemas.StepVariantSelectRequest) -> schemas.StepComparisonGroupRead:
    task = get_task_or_404(db, task_id)
    group = get_comparison_group_or_404(db, task_id, comparison_group_id)
    ensure_group_selectable(group)
    selected = get_step_or_404(db, task_id, payload.selected_step_id)
    ensure_step_variant_belongs_to_group(selected, group)
    previous = current_progress_percent(db, task_id)

    for variant in list_group_variants(db, group):
        if variant.id == selected.id:
            variant.branch_status = "selected"
            variant.is_selected_variant = True
            variant.selected_variant = True
            variant.is_active = True
        else:
            variant.branch_status = "not_selected"
            variant.is_selected_variant = False
            variant.selected_variant = False
            variant.is_active = False
    group.status = "resolved"
    group.selection_status = "resolved"
    group.selected_step_id = selected.id
    group.resolved_at = models.utcnow()
    record_event(db, task_id, "step_variant_selected", {"comparison_group_id": group.id, "selected_step_id": selected.id, "note": payload.note, "actor_id": payload.actor_id}, step_id=selected.id)
    record_event(db, task_id, "comparison_group_resolved", {"comparison_group_id": group.id, "selected_step_id": selected.id})
    update_task_completion_status(db, task)
    recalculate_progress_event(db, task_id, "step_variant_selected", previous)
    commit_and_write_task_log(db, task_id)
    db.refresh(group)
    return comparison_group_to_schema(db, group)


def abandon_step_variant(db: Session, task_id: int, step_id: int, payload: schemas.StepVariantAbandonRequest) -> models.Step:
    get_task_or_404(db, task_id)
    step = get_step_or_404(db, task_id, step_id)
    if step.comparison_group_id is None or step.branch_status == "selected":
        raise HTTPException(status_code=400, detail="Only unselected comparison variants can be abandoned")
    previous = current_progress_percent(db, task_id)
    step.branch_status = "abandoned"
    step.is_active = False
    step.is_selected_variant = False
    step.selected_variant = False
    record_event(db, task_id, "step_variant_abandoned", {"step_id": step.id, "reason": payload.reason, "actor_id": payload.actor_id}, step_id=step.id)
    recalculate_progress_event(db, task_id, "step_variant_abandoned", previous)
    commit_and_write_task_log(db, task_id)
    db.refresh(step)
    return step


def create_step_run_without_commit(
    db: Session,
    task: models.Task,
    step: models.Step,
    payload: schemas.StepRunCreate | schemas.StepRerunBranchRequest,
    event_type: str,
    event_payload: dict[str, Any] | None = None,
) -> models.StepRun:
    max_attempt = db.query(func.max(models.StepRun.attempt_number)).filter(models.StepRun.step_id == step.id).scalar()
    attempt_number = (max_attempt or 0) + 1
    run = models.StepRun(
        task_id=task.id,
        step_id=step.id,
        attempt_number=attempt_number,
        executor_type=payload.executor_type,
        executor_ref=payload.executor_ref,
        status="running",
        input=encode_json(payload.input),
        started_at=models.utcnow(),
    )
    db.add(run)
    db.flush()
    task.status = "running"
    step.status = "running"
    payload_data = {"run_id": run.id, "attempt_number": run.attempt_number}
    if event_payload:
        payload_data.update(event_payload)
    record_event(db, task.id, event_type, payload_data, step_id=step.id, run_id=run.id)
    return run


def create_step_run(db: Session, task_id: int, step_id: int, payload: schemas.StepRunCreate, rerun: bool = False) -> models.StepRun:
    ensure_executor_type(payload.executor_type)
    task = get_task_or_404(db, task_id)
    step = get_step_or_404(db, task_id, step_id)
    ensure_step_can_run(db, step)
    event_type = "step_rerun_created" if rerun else "step_run_started"
    run = create_step_run_without_commit(db, task, step, payload, event_type)
    recalculate_progress_event(db, task_id, event_type)
    commit_and_write_task_log(db, task_id)
    db.refresh(run)
    return run


def list_step_runs(db: Session, task_id: int, step_id: int) -> list[models.StepRun]:
    get_step_or_404(db, task_id, step_id)
    return db.query(models.StepRun).filter(models.StepRun.task_id == task_id, models.StepRun.step_id == step_id).order_by(models.StepRun.attempt_number).all()


def complete_step_run_automatically(db: Session, task_id: int, step_id: int, run_id: int, output: dict[str, Any]) -> models.StepRun:
    task = get_task_or_404(db, task_id)
    step = get_step_or_404(db, task_id, step_id)
    run = get_run_or_404(db, task_id, step_id, run_id)
    if run.status != "running":
        raise HTTPException(status_code=400, detail="Only running runs can be completed automatically")

    previous = current_progress_percent(db, task_id)
    run.output = encode_json(output)
    run.error = None
    run.submitted_at = models.utcnow()
    run.ended_at = models.utcnow()
    set_run_duration(run, run.submitted_at)
    run.status = "accepted"
    step.status = "approved"
    step.approved_run_id = run.id
    record_event(db, task_id, "step_run_submitted", {"run_id": run.id, "automatic": True}, step_id=step_id, run_id=run.id)
    record_event(db, task_id, "step_auto_approved", {"run_id": run.id, "step_id": step.id}, step_id=step_id, run_id=run.id)
    record_event(db, task_id, "step_approved", {"step_id": step_id, "approved_run_id": run_id}, step_id=step_id, run_id=run_id)
    update_task_completion_status(db, task)
    recalculate_progress_event(db, task_id, "step_auto_approved", previous)
    commit_and_write_task_log(db, task_id)
    db.refresh(run)
    return run


def fail_step_run(db: Session, task_id: int, step_id: int, run_id: int, error: str) -> models.StepRun:
    task = get_task_or_404(db, task_id)
    step = get_step_or_404(db, task_id, step_id)
    run = get_run_or_404(db, task_id, step_id, run_id)
    if run.status != "running":
        raise HTTPException(status_code=400, detail="Only running runs can fail")

    previous = current_progress_percent(db, task_id)
    run.status = "failed"
    run.error = error
    run.ended_at = models.utcnow()
    set_run_duration(run, run.ended_at)
    step.status = "failed"
    task.status = "failed"
    record_event(db, task_id, "step_run_failed", {"run_id": run.id, "error": error}, step_id=step_id, run_id=run.id)
    recalculate_progress_event(db, task_id, "step_run_failed", previous)
    commit_and_write_task_log(db, task_id)
    db.refresh(run)
    return run


def mark_step_run_incomplete_for_retry(db: Session, task_id: int, step_id: int, run_id: int, output: dict[str, Any], reason: str) -> models.StepRun:
    task = get_task_or_404(db, task_id)
    step = get_step_or_404(db, task_id, step_id)
    run = get_run_or_404(db, task_id, step_id, run_id)
    if run.status != "running":
        raise HTTPException(status_code=400, detail="Only running runs can be marked incomplete")

    previous = current_progress_percent(db, task_id)
    run.status = "rejected"
    run.output = encode_json(output)
    run.error = reason
    run.ended_at = models.utcnow()
    set_run_duration(run, run.ended_at)
    task.status = "needs_revision"
    step.status = "needs_revision"
    record_event(db, task_id, "codex_result_incomplete", {"run_id": run.id, "reason": reason}, step_id=step_id, run_id=run.id)
    recalculate_progress_event(db, task_id, "codex_result_incomplete", previous)
    commit_and_write_task_log(db, task_id)
    db.refresh(run)
    return run


def submit_step_run(db: Session, task_id: int, step_id: int, run_id: int, payload: schemas.StepRunSubmit) -> models.StepRun:
    task = get_task_or_404(db, task_id)
    step = get_step_or_404(db, task_id, step_id)
    run = get_run_or_404(db, task_id, step_id, run_id)
    if run.status != "running":
        raise HTTPException(status_code=400, detail="Only running runs can be submitted")
    run.output = encode_json(payload.output)
    run.error = payload.error
    run.submitted_at = models.utcnow()
    set_run_duration(run, run.submitted_at)
    if step.requires_approval:
        run.status = "submitted"
        task.status = "waiting_review"
        step.status = "waiting_review"
        record_event(db, task_id, "step_run_submitted", {"run_id": run.id}, step_id=step_id, run_id=run.id)
    else:
        run.status = "accepted"
        run.ended_at = models.utcnow()
        set_run_duration(run, run.ended_at)
        step.status = "approved"
        step.approved_run_id = run.id
        record_event(db, task_id, "step_run_submitted", {"run_id": run.id}, step_id=step_id, run_id=run.id)
        record_event(db, task_id, "step_auto_approved", {"run_id": run.id, "step_id": step.id}, step_id=step_id, run_id=run.id)
        update_task_completion_status(db, task)
        recalculate_progress_event(db, task_id, "step_auto_approved")
    commit_and_write_task_log(db, task_id)
    db.refresh(run)
    return run


def review_step_run(db: Session, task_id: int, step_id: int, run_id: int, payload: schemas.StepRunReview) -> models.Approval:
    ensure_executor_type(payload.reviewed_by_type)
    task = get_task_or_404(db, task_id)
    step = get_step_or_404(db, task_id, step_id)
    run = get_run_or_404(db, task_id, step_id, run_id)
    if run.status != "submitted":
        raise HTTPException(status_code=400, detail="Only submitted runs can be reviewed")
    approval = models.Approval(
        task_id=task_id,
        step_id=step_id,
        run_id=run_id,
        decision=payload.decision,
        comment=payload.comment,
        reviewed_by_type=payload.reviewed_by_type,
        reviewed_by_id=payload.reviewed_by_id,
    )
    db.add(approval)

    if payload.decision == "approved":
        run.status = "accepted"
        run.ended_at = models.utcnow()
        set_run_duration(run, run.ended_at)
        step.status = "approved"
        step.approved_run_id = run_id
        record_event(db, task_id, "step_run_reviewed", {"run_id": run_id, "decision": payload.decision}, step_id=step_id, run_id=run_id)
        record_event(db, task_id, "step_approved", {"step_id": step_id, "approved_run_id": run_id}, step_id=step_id, run_id=run_id)
        update_task_completion_status(db, task)
    else:
        run.status = "rejected"
        run.ended_at = models.utcnow()
        set_run_duration(run, run.ended_at)
        task.status = "needs_revision"
        step.status = "needs_revision"
        record_event(db, task_id, "step_run_reviewed", {"run_id": run_id, "decision": payload.decision}, step_id=step_id, run_id=run_id)
        record_event(db, task_id, "step_needs_revision", {"step_id": step_id, "run_id": run_id}, step_id=step_id, run_id=run_id)

    recalculate_progress_event(db, task_id, "step_run_reviewed")
    commit_and_write_task_log(db, task_id)
    db.refresh(approval)
    return approval


def rerun_variant_label(db: Session, task_id: int, source: models.Step) -> str:
    existing_count = db.query(func.count(models.Step.id)).filter(models.Step.task_id == task_id, models.Step.forked_from_step_id == source.id).scalar() or 0
    return f"rerun-{existing_count + 1}"


def rerun_step(db: Session, task_id: int, step_id: int, payload: schemas.StepRerunBranchRequest) -> schemas.StepRerunBranchResponse:
    ensure_executor_type(payload.executor_type)
    ensure_executor_type(payload.created_by_type)
    task = get_task_or_404(db, task_id)
    if task.status in {"archived", "cancelled"}:
        raise HTTPException(status_code=400, detail=f"Task status {task.status} does not allow rerun branches")
    source = get_step_or_404(db, task_id, step_id)
    ensure_step_can_rerun(db, source)
    previous = current_progress_percent(db, task_id)
    clone_batch_id = str(uuid.uuid4())
    objective = payload.objective or source.objective
    if payload.change_request and payload.change_request.strip():
        objective = f"{objective}\n\nChange request: {payload.change_request.strip()}"
    fork_payload = schemas.StepForkRequest(
        variant_label=payload.variant_label or rerun_variant_label(db, task_id, source),
        title=payload.title or source.title,
        objective=objective,
        fork_reason=payload.fork_reason or f"Rerun branch from step {source.id}",
        clone_subtree=False,
        forked_from_run_id=source.approved_run_id or latest_step_run_id(db, source.id),
        created_by_type=payload.created_by_type,
        created_by_id=payload.created_by_id,
    )
    ensure_step_graph_backfilled(db, task_id)
    group, forked = create_forked_step_without_commit(db, task_id, source, fork_payload, clone_batch_id=clone_batch_id, create_comparison_group=False)
    comparison_group_id = group.id if group else None
    cloned_count = clone_downstream_steps_for_branch(db, task_id, source, forked)
    record_event(
        db,
        task_id,
        "step_rerun_branch_created",
        {"source_step_id": source.id, "comparison_group_id": comparison_group_id, "forked_step_id": forked.id},
        step_id=forked.id,
    )
    normalize_step_order(db, task_id)
    recalculate_progress_event(db, task_id, "step_rerun_branch_created", previous)
    commit_and_write_task_log(db, task_id)
    db.refresh(forked)
    return schemas.StepRerunBranchResponse(comparison_group_id=comparison_group_id, forked_step_id=forked.id, cloned_steps_count=cloned_count)


def reset_downstream_steps_for_rerun(db: Session, task_id: int, step: models.Step) -> None:
    ensure_step_graph_backfilled(db, task_id)
    for downstream in graph_continuation_steps(db, task_id, step):
        if downstream.status in {"approved", "skipped", "needs_revision", "failed"}:
            downstream.status = "pending"
            downstream.approved_run_id = None


def retry_step_run_in_place(db: Session, task_id: int, step_id: int, payload: schemas.StepRunCreate) -> models.StepRun:
    ensure_executor_type(payload.executor_type)
    task = get_task_or_404(db, task_id)
    step = get_step_or_404(db, task_id, step_id)
    if not step.is_active or step.status == "superseded":
        raise HTTPException(status_code=400, detail="Inactive or superseded steps cannot retry in place")
    if step.branch_status in EXCLUDED_BRANCH_STATUSES:
        raise HTTPException(status_code=400, detail="Inactive step variants cannot retry in place")
    if step.status not in IN_PLACE_RETRY_STEP_STATUSES:
        raise HTTPException(status_code=400, detail=f"Step status {step.status} cannot retry in place")
    if not dependencies_satisfied(db, step):
        raise HTTPException(status_code=400, detail="Step dependencies are not satisfied")
    if has_running_or_review_step(db, task_id, exclude_step_id=step.id):
        raise HTTPException(status_code=400, detail="Cannot retry while another step is running or waiting for review")
    ensure_step_attempt_limit(db, step)
    step.approved_run_id = None
    reset_downstream_steps_for_rerun(db, task_id, step)
    previous = current_progress_percent(db, task_id)
    run = create_step_run_without_commit(db, task, step, payload, "step_rerun_created")
    recalculate_progress_event(db, task_id, "step_rerun_created", previous)
    commit_and_write_task_log(db, task_id)
    db.refresh(run)
    return run


CAPABILITY_REGISTRY: dict[str, schemas.CapabilityDefinitionRead] = {
    item["capability_id"]: schemas.CapabilityDefinitionRead(**item)
    for item in [
        {
            "capability_id": "generate_report",
            "name": "Generate report",
            "description": "Record a report-generation capability invocation.",
            "adapter_id": "record_only",
            "handler_name": "generate_report",
            "requires_approval": False,
            "input_schema": {"topic": "string"},
            "output_schema": {"summary": "string"},
        },
        {
            "capability_id": "run_tests",
            "name": "Run tests",
            "description": "Record a test-running capability invocation without executing tests.",
            "adapter_id": "record_only",
            "handler_name": "run_tests",
            "requires_approval": True,
            "input_schema": {"scope": "string"},
            "output_schema": {"result": "string"},
        },
        {
            "capability_id": "call_codex",
            "name": "Call Codex",
            "description": "Record a Codex adapter invocation without calling Codex.",
            "adapter_id": "record_only",
            "handler_name": "call_codex",
            "requires_approval": True,
            "input_schema": {"prompt": "string"},
            "output_schema": {"summary": "string"},
        },
        {
            "capability_id": "scan_source",
            "name": "Scan source",
            "description": "Record a source scanning capability invocation without reading files.",
            "adapter_id": "record_only",
            "handler_name": "scan_source",
            "requires_approval": True,
            "input_schema": {"scope": "string"},
            "output_schema": {"summary": "string"},
        },
        {
            "capability_id": "query_database",
            "name": "Query database",
            "description": "Record a database query capability invocation without executing queries.",
            "adapter_id": "record_only",
            "handler_name": "query_database",
            "requires_approval": True,
            "input_schema": {"query": "string"},
            "output_schema": {"summary": "string"},
        },
        {
            "capability_id": "browse_url",
            "name": "Browse URL",
            "description": "Record a browsing capability invocation without opening a browser.",
            "adapter_id": "record_only",
            "handler_name": "browse_url",
            "requires_approval": True,
            "input_schema": {"url": "string"},
            "output_schema": {"summary": "string"},
        },
        {
            "capability_id": "export_openapi",
            "name": "Export OpenAPI",
            "description": "Record an OpenAPI export capability invocation.",
            "adapter_id": "record_only",
            "handler_name": "export_openapi",
            "requires_approval": False,
            "input_schema": {},
            "output_schema": {"uri": "string"},
        },
    ]
}


def list_capabilities() -> list[schemas.CapabilityDefinitionRead]:
    return list(CAPABILITY_REGISTRY.values())


def get_capability_or_404(capability_id: str) -> schemas.CapabilityDefinitionRead:
    capability = CAPABILITY_REGISTRY.get(capability_id)
    if capability is None:
        raise HTTPException(status_code=404, detail="Capability not found")
    return capability


def list_artifacts(db: Session, task_id: int) -> list[models.Artifact]:
    get_task_or_404(db, task_id)
    return db.query(models.Artifact).filter(models.Artifact.task_id == task_id).order_by(models.Artifact.created_at, models.Artifact.id).all()


def create_capability_invocation(db: Session, task_id: int, step_id: int, run_id: int, payload: schemas.CapabilityInvocationCreate) -> models.CapabilityInvocation:
    ensure_executor_type(payload.invoked_by_type)
    get_run_or_404(db, task_id, step_id, run_id)
    capability = get_capability_or_404(payload.capability_id)
    invocation = models.CapabilityInvocation(
        task_id=task_id,
        step_id=step_id,
        run_id=run_id,
        invoked_by_type=payload.invoked_by_type,
        invoked_by_id=payload.invoked_by_id,
        capability_id=capability.capability_id,
        capability_name=capability.name,
        adapter_id=capability.adapter_id,
        handler_name=capability.handler_name,
        status="pending",
        input=encode_json(payload.input),
    )
    db.add(invocation)
    db.flush()
    record_event(db, task_id, "capability_invocation_recorded", {"capability_invocation_id": invocation.id, "capability_id": invocation.capability_id}, step_id=step_id, run_id=run_id, capability_invocation_id=invocation.id)
    commit_and_write_task_log(db, task_id)
    db.refresh(invocation)
    return invocation


def get_capability_invocation_or_404(db: Session, task_id: int, invocation_id: int) -> models.CapabilityInvocation:
    invocation = db.get(models.CapabilityInvocation, invocation_id)
    if invocation is None or invocation.task_id != task_id:
        raise HTTPException(status_code=404, detail="Capability invocation not found")
    return invocation


def update_capability_invocation(db: Session, task_id: int, invocation_id: int, payload: schemas.CapabilityInvocationUpdate) -> models.CapabilityInvocation:
    invocation = get_capability_invocation_or_404(db, task_id, invocation_id)
    invocation.status = payload.status
    invocation.output = encode_json(payload.output) if payload.output is not None else None
    invocation.error = payload.error
    invocation.duration_ms = payload.duration_ms
    invocation.artifacts_json = encode_json([artifact.model_dump() for artifact in payload.artifacts])
    terminal_at = models.utcnow() if payload.status in {"succeeded", "failed", "blocked", "cancelled"} else None
    invocation.completed_at = terminal_at
    invocation.ended_at = terminal_at
    for artifact_payload in payload.artifacts:
        artifact = models.Artifact(
            task_id=task_id,
            step_id=invocation.step_id,
            run_id=invocation.run_id,
            capability_invocation_id=invocation.id,
            type=artifact_payload.type,
            name=artifact_payload.name,
            uri=artifact_payload.uri,
            metadata_json=encode_json(artifact_payload.metadata),
        )
        db.add(artifact)
        db.flush()
        record_event(db, task_id, "artifact_created", {"artifact_id": artifact.id, "capability_invocation_id": invocation.id}, step_id=invocation.step_id, run_id=invocation.run_id, capability_invocation_id=invocation.id)
    record_event(db, task_id, "capability_invocation_updated", {"capability_invocation_id": invocation.id, "status": invocation.status}, step_id=invocation.step_id, run_id=invocation.run_id, capability_invocation_id=invocation.id)
    commit_and_write_task_log(db, task_id)
    db.refresh(invocation)
    return invocation


def list_capability_invocations(db: Session, task_id: int) -> list[models.CapabilityInvocation]:
    get_task_or_404(db, task_id)
    return db.query(models.CapabilityInvocation).filter(models.CapabilityInvocation.task_id == task_id).order_by(models.CapabilityInvocation.created_at, models.CapabilityInvocation.id).all()


def list_run_capability_invocations(db: Session, task_id: int, step_id: int, run_id: int) -> list[models.CapabilityInvocation]:
    get_run_or_404(db, task_id, step_id, run_id)
    return (
        db.query(models.CapabilityInvocation)
        .filter(models.CapabilityInvocation.task_id == task_id, models.CapabilityInvocation.step_id == step_id, models.CapabilityInvocation.run_id == run_id)
        .order_by(models.CapabilityInvocation.created_at, models.CapabilityInvocation.id)
        .all()
    )


def list_timeline(db: Session, task_id: int) -> list[models.Event]:
    get_task_or_404(db, task_id)
    return db.query(models.Event).filter(models.Event.task_id == task_id).order_by(models.Event.created_at, models.Event.id).all()


def run_to_schema(run: models.StepRun) -> schemas.StepRunRead:
    return schemas.StepRunRead(
        id=run.id,
        task_id=run.task_id,
        step_id=run.step_id,
        attempt_number=run.attempt_number,
        executor_type=run.executor_type,
        executor_ref=run.executor_ref,
        status=run.status,
        input=decode_json(run.input) or {},
        output=decode_json(run.output),
        error=run.error,
        started_at=run.started_at,
        submitted_at=run.submitted_at,
        ended_at=run.ended_at,
        duration_ms=run_consumed_ms(run, models.utcnow()),
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def artifact_to_schema(artifact: models.Artifact) -> schemas.ArtifactRead:
    return schemas.ArtifactRead(
        id=artifact.id,
        task_id=artifact.task_id,
        step_id=artifact.step_id,
        run_id=artifact.run_id,
        capability_invocation_id=artifact.capability_invocation_id,
        type=artifact.type,
        name=artifact.name,
        uri=artifact.uri,
        metadata=decode_json(artifact.metadata_json) or {},
        created_at=artifact.created_at,
    )


def capability_invocation_to_schema(invocation: models.CapabilityInvocation) -> schemas.CapabilityInvocationRead:
    return schemas.CapabilityInvocationRead(
        id=invocation.id,
        task_id=invocation.task_id,
        step_id=invocation.step_id,
        run_id=invocation.run_id,
        invoked_by_type=invocation.invoked_by_type,
        invoked_by_id=invocation.invoked_by_id,
        capability_id=invocation.capability_id,
        capability_name=invocation.capability_name,
        adapter_id=invocation.adapter_id,
        handler_name=invocation.handler_name,
        status=invocation.status,
        input=decode_json(invocation.input),
        output=decode_json(invocation.output),
        error=invocation.error,
        duration_ms=invocation.duration_ms,
        artifacts=decode_json(invocation.artifacts_json) or [],
        created_at=invocation.created_at,
        completed_at=invocation.completed_at,
        ended_at=invocation.ended_at,
    )


def event_to_schema(event: models.Event) -> schemas.EventRead:
    return schemas.EventRead(
        id=event.id,
        task_id=event.task_id,
        step_id=event.step_id,
        run_id=event.run_id,
        capability_invocation_id=event.capability_invocation_id,
        event_type=event.event_type,
        payload=decode_json(event.payload) or {},
        created_at=event.created_at,
    )
