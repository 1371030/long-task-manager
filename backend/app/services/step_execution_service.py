import json
from typing import Any

from fastapi import HTTPException
from openai import OpenAI

from .. import models, schemas
from ..config import settings
from ..db import SessionLocal
from . import codex_execution_service, task_service
from .plan_generation_service import PLANNER_USER_AGENT


def build_step_execution_prompt(
    task: models.Task,
    step: models.Step,
    run_input: dict[str, Any],
    previous_steps: list[models.Step],
) -> str:
    completed_context = "\n".join(
        f"- {item.step_order}. {item.title}: {item.objective}"
        for item in previous_steps
        if item.status == "approved"
    ) or "- No previous approved steps."
    return (
        "Execute the current step for this long-running task. "
        "Return only JSON with keys summary and details. "
        "Do not claim to run shell commands, edit files, use Codex, use GitHub, deploy, or modify source code. "
        "Only provide the textual result for this workflow step.\n\n"
        f"Task title: {task.title}\n"
        f"Task goal: {task.goal}\n"
        f"Task constraints: {task.constraints or 'None'}\n"
        f"Current step {step.step_order}: {step.title}\n"
        f"Step objective: {step.objective}\n"
        f"Run input: {json.dumps(run_input, ensure_ascii=False)}\n"
        f"Previous approved steps:\n{completed_context}"
    )


def step_llm_call_payload(
    task: models.Task,
    step: models.Step,
    run_input: dict[str, Any],
    previous_steps: list[models.Step],
) -> dict[str, Any]:
    request_messages = [
        {"role": "system", "content": "You execute workflow steps and return strict JSON."},
        {"role": "user", "content": build_step_execution_prompt(task, step, run_input, previous_steps)},
    ]
    return {
        "provider": "openai_compatible",
        "purpose": "step_execution",
        "base_url": settings.api_url,
        "model": settings.api_model,
        "temperature": settings.step_executor_openai_temperature,
        "timeout_seconds": settings.step_executor_openai_timeout_seconds,
        "response_format": {"type": "json_object"},
        "messages": request_messages,
    }


def execute_step(
    task: models.Task,
    step: models.Step,
    run_input: dict[str, Any],
    previous_steps: list[models.Step],
) -> dict[str, Any]:
    if not settings.api_key or not settings.api_model:
        raise HTTPException(status_code=503, detail="OpenAI-compatible step executor is not configured")

    client = OpenAI(
        api_key=settings.api_key,
        base_url=settings.api_url,
        timeout=settings.step_executor_openai_timeout_seconds,
        default_headers={"User-Agent": PLANNER_USER_AGENT},
    )
    llm_call = step_llm_call_payload(task, step, run_input, previous_steps)
    response = client.chat.completions.create(
        model=llm_call["model"],
        temperature=llm_call["temperature"],
        messages=llm_call["messages"],
        response_format=llm_call["response_format"],
    )
    content = response.choices[0].message.content
    if not content:
        raise HTTPException(status_code=502, detail="Step executor returned an empty response")

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="Step executor returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Step executor response must be a JSON object")
    if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
        raise HTTPException(status_code=502, detail="Step executor response must include a summary")

    payload.setdefault("model", settings.api_model)
    return payload


def approved_step_summaries(db, previous_steps: list[models.Step]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for previous_step in previous_steps:
        if previous_step.status != "approved" or previous_step.approved_run_id is None:
            continue
        approved_run = db.get(models.StepRun, previous_step.approved_run_id)
        output = task_service.decode_json(approved_run.output) if approved_run and approved_run.output else {}
        summary = None
        if isinstance(output, dict):
            details = output.get("details")
            hook_payload = details.get("hook_payload") if isinstance(details, dict) else None
            if isinstance(hook_payload, str):
                try:
                    hook_data = json.loads(hook_payload)
                    summary = hook_data.get("last_assistant_message") if isinstance(hook_data, dict) else None
                except json.JSONDecodeError:
                    summary = hook_payload
            summary = summary or output.get("summary")
        summaries.append({"step_order": previous_step.step_order, "title": previous_step.title, "summary": summary})
    return summaries


def execute_step_run_background(task_id: int, step_id: int, run_id: int) -> None:
    with SessionLocal() as db:
        try:
            task = task_service.get_task_or_404(db, task_id)
            step = task_service.get_step_or_404(db, task_id, step_id)
            run = task_service.get_run_or_404(db, task_id, step_id, run_id)
            run_input = task_service.decode_json(run.input) or {}
            task_service.ensure_step_graph_backfilled(db, task_id)
            previous_steps = task_service.previous_graph_steps(db, task_id, step)
            if codex_execution_service.should_use_codex(task):
                previous_step_summaries = approved_step_summaries(db, previous_steps)
                task_service.record_event(
                    db,
                    task_id,
                    "llm_call",
                    {
                        "provider": "codex_cli",
                        "purpose": "codex_step_execution",
                        "command": settings.codex_command,
                        "sandbox": settings.codex_sandbox,
                        "approval_policy": settings.codex_approval_policy,
                        "tmux_session": task.codex_tmux_session,
                        "prompt": codex_execution_service.build_prompt(task, step, run, run_input, previous_step_summaries),
                    },
                    step_id=step_id,
                    run_id=run_id,
                )
                metadata = codex_execution_service.start_codex_tmux(task, step, run, run_input, previous_step_summaries)
                run.executor_type = "codex"
                run.output = task_service.encode_json({"executor": "codex", "status": "launched", **metadata})
                task_service.record_event(db, task_id, "codex_run_launched", metadata, step_id=step_id, run_id=run_id)
                task_service.commit_and_write_task_log(db, task_id)
                return
            task_service.record_event(db, task_id, "llm_call", step_llm_call_payload(task, step, run_input, previous_steps), step_id=step_id, run_id=run_id)
            output = execute_step(task, step, run_input, previous_steps)
            task_service.complete_step_run_automatically(db, task_id, step_id, run_id, output)
        except Exception as exc:
            db.rollback()
            try:
                task_service.fail_step_run(db, task_id, step_id, run_id, str(exc))
            except Exception:
                db.rollback()


def next_auto_run_graph_step(db, task_id: int, current_step_id: int | None = None, scoped: bool = False) -> models.Step | None:
    if current_step_id is None:
        return None if scoped else task_service.next_startable_step(db, task_id)
    current_step = db.get(models.Step, current_step_id)
    if current_step is None or current_step.task_id != task_id:
        return None
    for successor in task_service.graph_successors(db, task_id, current_step):
        if successor.status in task_service.STARTABLE_STEP_STATUSES and task_service.dependencies_satisfied(db, successor):
            return successor
    return None


def execute_next_auto_run_step(
    task_id: int,
    executor_type: str = "agent",
    executor_ref: str | None = None,
    run_input: dict[str, Any] | None = None,
    current_step_id: int | None = None,
) -> bool:
    with SessionLocal() as db:
        task = task_service.get_task_or_404(db, task_id)
        if task.status in {"failed", "archived", "cancelled"}:
            return False
        next_input = run_input or {"instruction": "Automatically execute this step as part of task auto-run."}
        next_input = {**next_input, "auto_run": True}
        scoped = "auto_run_start_step_id" in next_input
        next_step = next_auto_run_graph_step(db, task_id, current_step_id=current_step_id, scoped=scoped)
        if next_step is None:
            return False
        run = task_service.create_step_run(
            db,
            task_id,
            next_step.id,
            schemas.StepRunCreate(
                executor_type=executor_type,
                executor_ref=executor_ref,
                input=next_input,
            ),
        )
        next_step_id = next_step.id
        next_run_id = run.id
    execute_step_run_background(task_id, next_step_id, next_run_id)
    return True


def execute_task_auto_run_background(
    task_id: int,
    initial_step_id: int,
    initial_run_id: int,
    executor_type: str = "agent",
    executor_ref: str | None = None,
    run_input: dict[str, Any] | None = None,
) -> None:
    current_step_id = initial_step_id
    current_run_id = initial_run_id
    next_run_input = run_input or {"instruction": "Automatically execute this step as part of task auto-run."}
    next_run_input = {**next_run_input, "auto_run": True}

    while True:
        execute_step_run_background(task_id, current_step_id, current_run_id)
        with SessionLocal() as db:
            current_run = task_service.get_run_or_404(db, task_id, current_step_id, current_run_id)
            if current_run.status == "running":
                return
            task = task_service.get_task_or_404(db, task_id)
            scoped = "auto_run_start_step_id" in next_run_input
            if task.status in {"failed", "archived", "cancelled"} or (task.status == "completed" and not scoped):
                return
            next_step = next_auto_run_graph_step(db, task_id, current_step_id=current_step_id, scoped=scoped)
            if next_step is None:
                return
            run = task_service.create_step_run(
                db,
                task_id,
                next_step.id,
                schemas.StepRunCreate(
                    executor_type=executor_type,
                    executor_ref=executor_ref,
                    input=next_run_input,
                ),
            )
            current_step_id = next_step.id
            current_run_id = run.id
