from datetime import datetime

from sqlalchemy.orm import Session

from .. import models
from ..schemas import ProgressSummary

EXCLUDED_BRANCH_STATUSES = {"not_selected", "abandoned", "superseded"}


def duration_ms_between(start: datetime | None, end: datetime | None) -> int:
    if start is None or end is None:
        return 0
    if start.tzinfo is None and end.tzinfo is not None:
        end = end.replace(tzinfo=None)
    elif start.tzinfo is not None and end.tzinfo is None:
        start = start.replace(tzinfo=None)
    return max(0, int((end - start).total_seconds() * 1000))


def run_consumed_ms(run: models.StepRun, now: datetime) -> int:
    if run.duration_ms is not None:
        return run.duration_ms
    end = run.submitted_at or run.ended_at or now
    return duration_ms_between(run.started_at, end)


def progress_eligible_steps(db: Session, task_id: int) -> list[models.Step]:
    active_steps = db.query(models.Step).filter(models.Step.task_id == task_id, models.Step.is_active.is_(True), models.Step.status != "superseded").all()
    groups = {
        group.id: group
        for group in db.query(models.StepComparisonGroup).filter(models.StepComparisonGroup.task_id == task_id).all()
    }
    eligible: list[models.Step] = []
    for step in active_steps:
        if step.branch_status in EXCLUDED_BRANCH_STATUSES:
            continue
        if step.comparison_group_id is None:
            eligible.append(step)
            continue
        group = groups.get(step.comparison_group_id)
        if group is None:
            continue
        status = group.status or group.selection_status
        if status == "resolved":
            if group.selected_step_id == step.id:
                eligible.append(step)
        elif status in {"open", "comparing"}:
            eligible.append(step)
    return eligible


def compute_progress(db: Session, task_id: int) -> ProgressSummary:
    active_steps = progress_eligible_steps(db, task_id)
    active_steps_total = len(active_steps)
    approved_or_skipped = sum(1 for step in active_steps if step.status in {"approved", "skipped"})
    progress_percent = 0.0 if active_steps_total == 0 else round(approved_or_skipped / active_steps_total * 100, 2)
    active_step_ids = [step.id for step in active_steps]
    runs = [] if not active_step_ids else db.query(models.StepRun).filter(models.StepRun.step_id.in_(active_step_ids)).all()
    now = models.utcnow()

    return ProgressSummary(
        active_steps_total=active_steps_total,
        approved_or_skipped_active_steps=approved_or_skipped,
        progress_percent=progress_percent,
        consumed_ms=sum(run_consumed_ms(run, now) for run in runs),
    )
