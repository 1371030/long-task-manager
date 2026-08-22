from sqlalchemy.orm import Session

from .. import models
from ..schemas import CurrentPointer, NextAction, NextActionApi

EXECUTOR_OPTIONS = ["human", "agent", "worker", "system"]
DECISION_OPTIONS = ["approved", "request_revision"]
COMPLETED_STEP_STATUSES = {"approved", "skipped"}
STEP_MUTATION_TASK_STATUSES = {"intake", "planning", "waiting_plan_review", "planned", "running", "waiting_review", "needs_revision", "blocked", "failed"}
STARTABLE_STEP_STATUSES = {"pending", "needs_revision", "failed"}


def ordered_active_steps(db: Session, task_id: int) -> list[models.Step]:
    return (
        db.query(models.Step)
        .filter(models.Step.task_id == task_id, models.Step.is_active.is_(True), models.Step.status != "superseded")
        .order_by(models.Step.step_order, models.Step.position, models.Step.id)
        .all()
    )


def dependencies_satisfied(db: Session, step: models.Step) -> bool:
    for dependency_id in step.depends_on_step_ids or []:
        dependency = db.get(models.Step, dependency_id)
        if dependency is None or dependency.task_id != step.task_id or dependency.status not in COMPLETED_STEP_STATUSES:
            return False
    return True


def clone_source_matches_branch(db: Session, candidate: models.Step, source_step: models.Step | None) -> bool:
    if candidate.cloned_from_step_id is None or source_step is None:
        return False
    cloned_source = db.get(models.Step, candidate.cloned_from_step_id)
    if cloned_source is None:
        return False
    if source_step.clone_batch_id is None:
        return cloned_source.clone_batch_id is None and not cloned_source.is_fork
    return cloned_source.clone_batch_id == source_step.clone_batch_id


def latest_accepted_step(db: Session, task_id: int, active_step_ids: list[int]) -> models.Step | None:
    if not active_step_ids:
        return None
    run = (
        db.query(models.StepRun)
        .filter(models.StepRun.task_id == task_id, models.StepRun.step_id.in_(active_step_ids), models.StepRun.status == "accepted")
        .order_by(models.StepRun.ended_at.desc(), models.StepRun.id.desc())
        .first()
    )
    return db.get(models.Step, run.step_id) if run else None


def next_branch_step_after(db: Session, steps: list[models.Step], latest_step: models.Step | None) -> models.Step | None:
    if latest_step is None or latest_step.comparison_group_id is None or latest_step.clone_batch_id is None:
        return None
    source_step = db.get(models.Step, latest_step.forked_from_step_id) if latest_step.forked_from_step_id else None
    for candidate in steps:
        if candidate.status in {"running", "waiting_review"}:
            return None
        if candidate.step_order <= latest_step.step_order:
            continue
        if candidate.comparison_group_id != latest_step.comparison_group_id:
            continue
        if candidate.clone_batch_id != latest_step.clone_batch_id:
            continue
        if candidate.status not in STARTABLE_STEP_STATUSES or not dependencies_satisfied(db, candidate):
            continue
        if clone_source_matches_branch(db, candidate, source_step):
            return candidate
    return None


def graph_ordered_steps(steps: list[models.Step]) -> list[models.Step]:
    by_id = {step.id: step for step in steps}
    roots = [step for step in steps if not any(previous_id in by_id for previous_id in step.previous_step_ids or [])]
    roots.sort(key=lambda item: (item.step_order, item.position, item.id))
    ordered: list[models.Step] = []
    seen: set[int] = set()

    def visit(step: models.Step) -> None:
        if step.id in seen:
            return
        seen.add(step.id)
        ordered.append(step)
        successors = [by_id[step_id] for step_id in step.next_step_ids or [] if step_id in by_id]
        successors.sort(key=lambda item: (item.step_order, item.position, item.id))
        for successor in successors:
            visit(successor)

    for root in roots:
        visit(root)
    for step in steps:
        visit(step)
    return ordered


def next_startable_step(db: Session, steps: list[models.Step]) -> models.Step | None:
    for step in steps:
        if step.status in {"running", "waiting_review"}:
            return None
    ordered_steps = graph_ordered_steps(steps)
    latest_step = latest_accepted_step(db, ordered_steps[0].task_id if ordered_steps else 0, [step.id for step in ordered_steps])
    branch_step = next_branch_step_after(db, ordered_steps, latest_step)
    if branch_step is not None:
        return branch_step
    for step in ordered_steps:
        if step.status in STARTABLE_STEP_STATUSES and dependencies_satisfied(db, step):
            return step
    return None


def attempts_available(db: Session, step: models.Step) -> bool:
    if step.max_attempts is None:
        return True
    attempts = db.query(models.StepRun).filter(models.StepRun.step_id == step.id).count()
    return attempts < step.max_attempts


def can_mutate_steps(task: models.Task | None) -> bool:
    return task is not None and task.status in STEP_MUTATION_TASK_STATUSES


def build_current_pointer(db: Session, task_id: int) -> CurrentPointer:
    active_steps = ordered_active_steps(db, task_id)
    active_step_ids = [step.id for step in active_steps]

    active_run = None
    if active_step_ids:
        active_run = (
            db.query(models.StepRun)
            .filter(models.StepRun.task_id == task_id, models.StepRun.step_id.in_(active_step_ids), models.StepRun.status.in_(["running", "submitted"]))
            .order_by(models.StepRun.updated_at.desc(), models.StepRun.id.desc())
            .first()
        )
    if active_run:
        invocation = (
            db.query(models.CapabilityInvocation)
            .filter(models.CapabilityInvocation.run_id == active_run.id)
            .order_by(models.CapabilityInvocation.created_at.desc(), models.CapabilityInvocation.id.desc())
            .first()
        )
        return CurrentPointer(
            task_id=task_id,
            step_id=active_run.step_id,
            run_id=active_run.id,
            capability_invocation_id=invocation.id if invocation else None,
        )

    next_step = next_startable_step(db, active_steps)
    if next_step is not None:
        return CurrentPointer(task_id=task_id, step_id=next_step.id)

    return CurrentPointer(task_id=task_id)


def build_next_actions(db: Session, task_id: int) -> list[NextAction]:
    task = db.get(models.Task, task_id)
    steps = ordered_active_steps(db, task_id)

    if task and task.status == "intake":
        return [
            NextAction(
                action_type="generate_plan",
                target_type="task",
                target={"task_id": task_id},
                label="Generate a step plan",
                api=NextActionApi(method="POST", path=f"/tasks/{task_id}/generate-plan"),
                requires_user_input=True,
                input_schema={
                    "generation_mode": ["manual", "auto"],
                    "steps": "array",
                    "instructions": "string",
                },
            )
        ]

    if task and task.status == "waiting_plan_review":
        return [
            NextAction(
                action_type="approve_plan",
                target_type="task",
                target={"task_id": task_id},
                label="Review and approve the plan",
                api=NextActionApi(method="POST", path=f"/tasks/{task_id}/approve-plan"),
                requires_user_input=True,
                input_schema={"decision": DECISION_OPTIONS},
            )
        ]

    workflow_actions: list[NextAction] = []
    comparison_actions: list[NextAction] = []
    structural_actions: list[NextAction] = []
    current_startable_step = next_startable_step(db, steps)

    for step in steps:
        runs = db.query(models.StepRun).filter(models.StepRun.step_id == step.id).order_by(models.StepRun.attempt_number).all()
        if step.status in STARTABLE_STEP_STATUSES and current_startable_step is not None and step.id == current_startable_step.id and attempts_available(db, step):
            workflow_actions.append(
                NextAction(
                    action_type="start_step_run" if step.status in {"pending", "failed"} else "rerun_step",
                    target_type="step",
                    target={"task_id": task_id, "step_id": step.id},
                    label="Start a step run" if step.status in {"pending", "failed"} else "Create a revised run for this step",
                    api=NextActionApi(
                        method="POST",
                        path=f"/tasks/{task_id}/steps/{step.id}/runs" if step.status in {"pending", "failed"} else f"/tasks/{task_id}/steps/{step.id}/rerun",
                    ),
                    requires_user_input=True,
                    input_schema={"executor_type": EXECUTOR_OPTIONS, "input": "object"},
                )
            )
        else:
            latest_run = runs[-1] if runs else None
            if latest_run and latest_run.status == "submitted" and step.requires_approval:
                workflow_actions.append(
                    NextAction(
                        action_type="review_step_run",
                        target_type="step_run",
                        target={"task_id": task_id, "step_id": step.id, "run_id": latest_run.id},
                        label="Review the submitted step run",
                        api=NextActionApi(method="POST", path=f"/tasks/{task_id}/steps/{step.id}/runs/{latest_run.id}/review"),
                        requires_user_input=True,
                        input_schema={"decision": DECISION_OPTIONS},
                    )
                )

        if runs:
            running_run = next((run for run in reversed(runs) if run.status == "running"), None)
            if running_run is not None:
                workflow_actions.append(
                    NextAction(
                        action_type="record_capability_invocation",
                        target_type="step_run",
                        target={"task_id": task_id, "step_id": step.id, "run_id": running_run.id},
                        label="Record a capability invocation",
                        api=NextActionApi(method="POST", path=f"/tasks/{task_id}/steps/{step.id}/runs/{running_run.id}/capability-invocations"),
                        requires_user_input=True,
                        input_schema={"capability_id": "string", "invoked_by_type": EXECUTOR_OPTIONS, "input": "object"},
                    )
                )

        if step.comparison_group_id is not None:
            group = db.get(models.StepComparisonGroup, step.comparison_group_id)
            group_status = (group.status or group.selection_status) if group else None
            if group and group_status in {"open", "comparing"}:
                if not any(action.target.get("comparison_group_id") == group.id and action.action_type == "compare_step_variants" for action in comparison_actions):
                    comparison_actions.append(
                        NextAction(
                            action_type="compare_step_variants",
                            target_type="comparison_group",
                            target={"task_id": task_id, "comparison_group_id": group.id},
                            label="Compare step variants",
                            api=NextActionApi(method="GET", path=f"/tasks/{task_id}/step-comparisons/{group.id}"),
                            requires_user_input=False,
                            input_schema={},
                        )
                    )
                    comparison_actions.append(
                        NextAction(
                            action_type="select_step_variant",
                            target_type="comparison_group",
                            target={"task_id": task_id, "comparison_group_id": group.id},
                            label="Select a step variant",
                            api=NextActionApi(method="POST", path=f"/tasks/{task_id}/step-comparisons/{group.id}/select"),
                            requires_user_input=True,
                            input_schema={"selected_step_id": "number", "note": "string"},
                        )
                    )
                if step.branch_status == "active" and not getattr(step, "is_selected_variant", False):
                    comparison_actions.append(
                        NextAction(
                            action_type="abandon_step_variant",
                            target_type="step",
                            target={"task_id": task_id, "step_id": step.id, "comparison_group_id": group.id},
                            label="Abandon this step variant",
                            api=NextActionApi(method="POST", path=f"/tasks/{task_id}/steps/{step.id}/abandon-variant"),
                            requires_user_input=True,
                            input_schema={"reason": "string"},
                        )
                    )

        if can_mutate_steps(task):
            structural_actions.extend(
                [
                    NextAction(
                        action_type="fork_step",
                        target_type="step",
                        target={"task_id": task_id, "step_id": step.id},
                        label="Fork this step into a variant",
                        api=NextActionApi(method="POST", path=f"/tasks/{task_id}/steps/{step.id}/fork"),
                        requires_user_input=True,
                        input_schema={"variant_label": "string", "title": "string", "description": "string", "clone_subtree": "boolean"},
                    ),
                    NextAction(
                        action_type="insert_step_after",
                        target_type="step",
                        target={"task_id": task_id, "step_id": step.id},
                        label="Insert a dynamic step after this step",
                        api=NextActionApi(method="POST", path=f"/tasks/{task_id}/steps"),
                        requires_user_input=True,
                        input_schema={"insert_mode": "insert_after_step", "target_step_id": step.id},
                    ),
                    NextAction(
                        action_type="supersede_step",
                        target_type="step",
                        target={"task_id": task_id, "step_id": step.id},
                        label="Supersede this step with a replacement",
                        api=NextActionApi(method="POST", path=f"/tasks/{task_id}/steps/{step.id}/supersede"),
                        requires_user_input=True,
                        input_schema={"new_step": {"title": "string", "description": "string"}},
                    ),
                    NextAction(
                        action_type="reorder_step",
                        target_type="step",
                        target={"task_id": task_id, "step_id": step.id},
                        label="Move this step in the active order",
                        api=NextActionApi(method="PATCH", path=f"/tasks/{task_id}/steps/{step.id}"),
                        requires_user_input=True,
                        input_schema={"step_order": "number"},
                    ),
                ]
            )
            if step.status in STARTABLE_STEP_STATUSES:
                structural_actions.append(
                    NextAction(
                        action_type="skip_step",
                        target_type="step",
                        target={"task_id": task_id, "step_id": step.id},
                        label="Skip this step",
                        api=NextActionApi(method="POST", path=f"/tasks/{task_id}/steps/{step.id}/skip"),
                        requires_user_input=True,
                        input_schema={"reason": "string"},
                    )
                )

    if can_mutate_steps(task):
        structural_actions.append(
            NextAction(
                action_type="add_step",
                target_type="task",
                target={"task_id": task_id},
                label="Add a dynamic step",
                api=NextActionApi(method="POST", path=f"/tasks/{task_id}/steps"),
                requires_user_input=True,
                input_schema={"title": "string", "description": "string", "insert_mode": "append_to_end"},
            )
        )

    return workflow_actions + comparison_actions + structural_actions
