from collections import Counter

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from . import task_service
from .progress_service import compute_progress, progress_eligible_steps

REVIEWABLE_TASK_STATUSES = {"planned", "running", "waiting_review", "needs_revision", "blocked", "failed", "completed"}


def classify_variance(variance_percentage_points: float) -> schemas.ProgressReviewClassification:
    if variance_percentage_points > 5:
        return "ahead"
    if variance_percentage_points < -5:
        return "behind"
    return "on_track"


def review_to_schema(review: models.TaskReview) -> schemas.ProgressReviewRead:
    return schemas.ProgressReviewRead(
        id=review.id,
        task_id=review.task_id,
        previous_review_id=review.previous_review_id,
        expected_progress_percent=review.expected_progress_percent,
        actual_progress_percent=review.actual_progress_percent,
        variance_percentage_points=review.variance_percentage_points,
        classification=review.classification,
        snapshot=task_service.decode_json(review.snapshot_json),
        observations=task_service.decode_json(review.observations_json),
        suggestions=task_service.decode_json(review.suggestions_json),
        decision=review.decision,
        decision_note=review.decision_note,
        decided_by_type=review.decided_by_type,
        decided_by_id=review.decided_by_id,
        decided_at=review.decided_at,
        created_by_type=review.created_by_type,
        created_by_id=review.created_by_id,
        created_at=review.created_at,
    )


def list_progress_reviews(db: Session, task_id: int) -> list[schemas.ProgressReviewRead]:
    task_service.get_task_or_404(db, task_id)
    reviews = (
        db.query(models.TaskReview)
        .filter(models.TaskReview.task_id == task_id)
        .order_by(models.TaskReview.created_at.desc(), models.TaskReview.id.desc())
        .all()
    )
    return [review_to_schema(review) for review in reviews]


def get_progress_review_or_404(db: Session, task_id: int, review_id: int) -> models.TaskReview:
    review = db.get(models.TaskReview, review_id)
    if review is None or review.task_id != task_id:
        raise HTTPException(status_code=404, detail="Progress review not found")
    return review


def build_review_analysis(
    db: Session,
    task: models.Task,
    expected_progress_percent: float,
) -> tuple[schemas.ProgressSummary, schemas.ProgressReviewClassification, float, dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    progress = compute_progress(db, task.id)
    eligible_steps = progress_eligible_steps(db, task.id)
    eligible_step_ids = [step.id for step in eligible_steps]
    runs = [] if not eligible_step_ids else db.query(models.StepRun).filter(models.StepRun.step_id.in_(eligible_step_ids)).all()
    step_status_counts = Counter(step.status for step in eligible_steps)
    run_status_counts = Counter(run.status for run in runs)
    latest_attempt_by_step: dict[int, int] = {}
    for run in runs:
        latest_attempt_by_step[run.step_id] = max(latest_attempt_by_step.get(run.step_id, 0), run.attempt_number)
    retry_count = sum(max(0, attempt_number - 1) for attempt_number in latest_attempt_by_step.values())
    variance = round(progress.progress_percent - expected_progress_percent, 2)
    classification = classify_variance(variance)
    snapshot = {
        "active_steps_total": progress.active_steps_total,
        "approved_or_skipped_active_steps": progress.approved_or_skipped_active_steps,
        "consumed_ms": progress.consumed_ms,
        "step_status_counts": dict(sorted(step_status_counts.items())),
        "run_status_counts": dict(sorted(run_status_counts.items())),
        "retry_count": retry_count,
        "dynamic_active_steps": sum(1 for step in eligible_steps if step.is_dynamic),
    }
    observations: list[dict[str, object]] = [
        {
            "code": f"progress_{classification}",
            "message": f"Actual progress is {abs(variance):.2f} percentage points {'above' if variance > 0 else 'below' if variance < 0 else 'equal to'} the expected progress.",
            "target_step_id": None,
        }
    ]
    suggestions: list[dict[str, object]] = []

    for step in eligible_steps:
        if step.status == "needs_revision":
            observations.append({"code": "step_needs_revision", "message": f"Step {step.id} needs revision.", "target_step_id": step.id})
            suggestions.append({"action_type": "rerun_step", "message": "Create a revised branch for this step.", "target_step_id": step.id, "api_path": f"/tasks/{task.id}/steps/{step.id}/rerun"})
        elif step.status == "failed":
            observations.append({"code": "step_failed", "message": f"Step {step.id} is failed.", "target_step_id": step.id})
            suggestions.append({"action_type": "retry_step", "message": "Retry this step with its current definition.", "target_step_id": step.id, "api_path": f"/tasks/{task.id}/steps/{step.id}/retry"})

    if run_status_counts.get("failed", 0):
        observations.append({"code": "failed_runs", "message": f"{run_status_counts['failed']} failed run(s) remain in the eligible execution history.", "target_step_id": None})
    if run_status_counts.get("rejected", 0):
        observations.append({"code": "rejected_runs", "message": f"{run_status_counts['rejected']} rejected run(s) indicate recorded rework.", "target_step_id": None})
    if retry_count:
        observations.append({"code": "retries_recorded", "message": f"Eligible steps contain {retry_count} retry attempt(s).", "target_step_id": None})
    if snapshot["dynamic_active_steps"]:
        observations.append({"code": "dynamic_scope", "message": f"The current progress denominator includes {snapshot['dynamic_active_steps']} dynamic step(s).", "target_step_id": None})
    if task.status == "blocked":
        observations.append({"code": "task_blocked", "message": "The task is currently blocked.", "target_step_id": None})
        suggestions.append({"action_type": "review_blocker", "message": "Review the blocker before continuing the plan.", "target_step_id": None, "api_path": None})
    if classification == "behind" and not suggestions:
        suggestions.append({"action_type": "review_remaining_steps", "message": "Review remaining step scope and use existing step controls if an adjustment is needed.", "target_step_id": None, "api_path": f"/tasks/{task.id}/steps"})
    elif classification != "behind" and not suggestions:
        suggestions.append({"action_type": "keep_plan", "message": "The current evidence does not require a structural plan change.", "target_step_id": None, "api_path": None})

    return progress, classification, variance, snapshot, observations, suggestions


def create_progress_review(db: Session, task_id: int, payload: schemas.ProgressReviewCreate) -> schemas.ProgressReviewRead:
    task = task_service.get_task_or_404(db, task_id)
    if task.status not in REVIEWABLE_TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"Task status {task.status} does not allow progress reviews")
    previous_review = (
        db.query(models.TaskReview)
        .filter(models.TaskReview.task_id == task_id)
        .order_by(models.TaskReview.created_at.desc(), models.TaskReview.id.desc())
        .first()
    )
    if previous_review is not None and previous_review.decision is None:
        raise HTTPException(status_code=400, detail="Decide the latest progress review before creating another")

    progress, classification, variance, snapshot, observations, suggestions = build_review_analysis(db, task, payload.expected_progress_percent)
    review = models.TaskReview(
        task_id=task_id,
        previous_review_id=previous_review.id if previous_review else None,
        expected_progress_percent=payload.expected_progress_percent,
        actual_progress_percent=progress.progress_percent,
        variance_percentage_points=variance,
        classification=classification,
        snapshot_json=task_service.encode_json(snapshot),
        observations_json=task_service.encode_json(observations),
        suggestions_json=task_service.encode_json(suggestions),
        created_by_type=payload.created_by_type,
        created_by_id=payload.created_by_id,
    )
    db.add(review)
    db.flush()
    task_service.record_event(
        db,
        task_id,
        "progress_review_created",
        {
            "review_id": review.id,
            "previous_review_id": review.previous_review_id,
            "expected_progress_percent": review.expected_progress_percent,
            "actual_progress_percent": review.actual_progress_percent,
            "variance_percentage_points": review.variance_percentage_points,
            "classification": review.classification,
        },
    )
    task_service.commit_and_write_task_log(db, task_id)
    db.refresh(review)
    return review_to_schema(review)


def decide_progress_review(
    db: Session,
    task_id: int,
    review_id: int,
    payload: schemas.ProgressReviewDecisionCreate,
) -> schemas.ProgressReviewRead:
    review = get_progress_review_or_404(db, task_id, review_id)
    if review.decision is not None:
        raise HTTPException(status_code=400, detail="Progress review has already been decided")
    review.decision = payload.decision
    review.decision_note = payload.note
    review.decided_by_type = payload.decided_by_type
    review.decided_by_id = payload.decided_by_id
    review.decided_at = models.utcnow()
    task_service.record_event(
        db,
        task_id,
        "progress_review_decided",
        {"review_id": review.id, "decision": review.decision, "note": review.decision_note},
    )
    task_service.commit_and_write_task_log(db, task_id)
    db.refresh(review)
    return review_to_schema(review)
