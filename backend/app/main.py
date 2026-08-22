import os

from fastapi import BackgroundTasks, Depends, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import models, schemas
from .db import Base, SessionLocal, engine, ensure_sqlite_schema, get_db
from .services import codex_execution_service, settings_service, step_execution_service, task_service

app = FastAPI(title="Long Task Manager", version="0.1.1")

default_cors_origins = "http://localhost:3000,http://127.0.0.1:3000,http://[::1]:3000,http://localhost:3001,http://127.0.0.1:3001,http://[::1]:3001"
cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", default_cors_origins).split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_schema()
    with SessionLocal() as db:
        settings_service.seed_planner_prompt(db)
        task_service.backfill_all_step_graphs(db)

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.1"}

@app.get("/settings/planner-prompt", response_model=schemas.PlannerPromptRead)
def get_planner_prompt(db: Session = Depends(get_db)) -> schemas.PlannerPromptRead:
    return settings_service.read_planner_prompt(db)


@app.patch("/settings/planner-prompt", response_model=schemas.PlannerPromptRead)
def update_planner_prompt(payload: schemas.PlannerPromptUpdate, db: Session = Depends(get_db)) -> schemas.PlannerPromptRead:
    return settings_service.update_planner_prompt(db, payload)


@app.get("/capabilities", response_model=list[schemas.CapabilityDefinitionRead])
def list_capabilities() -> list[schemas.CapabilityDefinitionRead]:
    return task_service.list_capabilities()


@app.get("/capabilities/{capability_id}", response_model=schemas.CapabilityDefinitionRead)
def get_capability(capability_id: str) -> schemas.CapabilityDefinitionRead:
    return task_service.get_capability_or_404(capability_id)


@app.post("/tasks", response_model=schemas.TaskRead)
def create_task(payload: schemas.TaskCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> schemas.TaskRead:
    task = task_service.create_task(db, payload)
    if task.executor_mode == "codex":
        background_tasks.add_task(codex_execution_service.start_task_codex_keepalive, task.id, task.project_path)
    return task_service.task_read_schema(task)


@app.get("/tasks", response_model=list[schemas.TaskRead])
def list_tasks(db: Session = Depends(get_db)) -> list[schemas.TaskRead]:
    return [task_service.task_read_schema(task) for task in task_service.list_tasks(db)]


@app.get("/tasks/{task_id}", response_model=schemas.TaskDetailResponse)
def get_task(task_id: int, db: Session = Depends(get_db)) -> schemas.TaskDetailResponse:
    codex_execution_service.sync_missing_task_tmux_session(db, task_id)
    return task_service.get_task_detail(db, task_id)


@app.post("/tasks/{task_id}/close", response_model=schemas.TaskDetailResponse)
def close_task(task_id: int, payload: schemas.TaskCloseRequest, db: Session = Depends(get_db)) -> schemas.TaskDetailResponse:
    return task_service.close_task(db, task_id, payload, codex_execution_service.kill_tmux_session)


@app.post("/tasks/{task_id}/messages", response_model=schemas.TaskMessageRead)
def add_task_message(task_id: int, payload: schemas.TaskMessageCreate, db: Session = Depends(get_db)) -> models.TaskMessage:
    return task_service.add_message(db, task_id, payload)


@app.post("/tasks/{task_id}/generate-plan", response_model=schemas.TaskDetailResponse)
def generate_plan(task_id: int, payload: schemas.GeneratePlanRequest, db: Session = Depends(get_db)) -> schemas.TaskDetailResponse:
    return task_service.generate_plan(db, task_id, payload)


@app.post("/tasks/{task_id}/approve-plan", response_model=schemas.TaskDetailResponse)
def approve_plan(task_id: int, payload: schemas.ApprovePlanRequest, db: Session = Depends(get_db)) -> schemas.TaskDetailResponse:
    return task_service.approve_plan(db, task_id, payload)


@app.post("/tasks/{task_id}/steps", response_model=schemas.StepRead)
def create_step(task_id: int, payload: schemas.StepCreate, db: Session = Depends(get_db)) -> schemas.StepRead:
    step = task_service.create_step(db, task_id, payload)
    return task_service.step_to_schema(step)


@app.get("/tasks/{task_id}/steps", response_model=list[schemas.StepRead])
def list_steps(task_id: int, db: Session = Depends(get_db)) -> list[schemas.StepRead]:
    return task_service.steps_to_schema(db, task_id, task_service.list_steps(db, task_id))


@app.patch("/tasks/{task_id}/steps/{step_id}", response_model=schemas.StepRead)
def update_step(task_id: int, step_id: int, payload: schemas.StepPatchRequest, db: Session = Depends(get_db)) -> schemas.StepRead:
    step = task_service.update_step(db, task_id, step_id, payload)
    return task_service.step_to_schema(step)


@app.post("/tasks/{task_id}/steps/{step_id}/skip", response_model=schemas.StepRead)
def skip_step(task_id: int, step_id: int, payload: schemas.StepSkipRequest, db: Session = Depends(get_db)) -> schemas.StepRead:
    step = task_service.skip_step(db, task_id, step_id, payload)
    return task_service.step_to_schema(step)


@app.post("/tasks/{task_id}/steps/{step_id}/supersede", response_model=schemas.StepRead)
def supersede_step(task_id: int, step_id: int, payload: schemas.StepSupersedeRequest, db: Session = Depends(get_db)) -> schemas.StepRead:
    step = task_service.supersede_step(db, task_id, step_id, payload)
    return task_service.step_to_schema(step)


@app.post("/tasks/{task_id}/steps/{step_id}/fork", response_model=schemas.StepForkResponse)
def fork_step(task_id: int, step_id: int, payload: schemas.StepForkRequest, db: Session = Depends(get_db)) -> schemas.StepForkResponse:
    return task_service.fork_step(db, task_id, step_id, payload)


@app.get("/tasks/{task_id}/step-comparisons/{comparison_group_id}", response_model=schemas.StepComparisonGroupRead)
def get_step_comparison(task_id: int, comparison_group_id: int, db: Session = Depends(get_db)) -> schemas.StepComparisonGroupRead:
    return task_service.get_step_comparison(db, task_id, comparison_group_id)


@app.post("/tasks/{task_id}/step-comparisons/{comparison_group_id}/select", response_model=schemas.StepComparisonGroupRead)
def select_step_variant(
    task_id: int,
    comparison_group_id: int,
    payload: schemas.StepVariantSelectRequest,
    db: Session = Depends(get_db),
) -> schemas.StepComparisonGroupRead:
    return task_service.select_step_variant(db, task_id, comparison_group_id, payload)


@app.post("/tasks/{task_id}/steps/{step_id}/abandon-variant", response_model=schemas.StepRead)
def abandon_step_variant(task_id: int, step_id: int, payload: schemas.StepVariantAbandonRequest, db: Session = Depends(get_db)) -> models.Step:
    return task_service.abandon_step_variant(db, task_id, step_id, payload)


@app.post("/tasks/{task_id}/steps/{step_id}/runs", response_model=schemas.StepRunRead)
def create_step_run(
    task_id: int,
    step_id: int,
    payload: schemas.StepRunCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> schemas.StepRunRead:
    run = task_service.create_step_run(db, task_id, step_id, payload)
    if run.executor_type != "human":
        background_tasks.add_task(step_execution_service.execute_step_run_background, task_id, step_id, run.id)
    return task_service.run_to_schema(run)


@app.post("/tasks/{task_id}/auto-run", response_model=schemas.AutoRunResponse)
def auto_run_task(
    task_id: int,
    payload: schemas.AutoRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> schemas.AutoRunResponse:
    task_service.get_task_or_404(db, task_id)
    step = task_service.next_startable_step(db, task_id)
    if step is None:
        return schemas.AutoRunResponse(task_id=task_id, started=False, message="No startable step")
    return start_auto_run_from_step(task_id, step.id, payload, background_tasks, db, scoped=False)


@app.post("/tasks/{task_id}/steps/{step_id}/auto-run", response_model=schemas.AutoRunResponse)
def auto_run_from_step(
    task_id: int,
    step_id: int,
    payload: schemas.AutoRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> schemas.AutoRunResponse:
    return start_auto_run_from_step(task_id, step_id, payload, background_tasks, db, scoped=True)


def start_auto_run_from_step(
    task_id: int,
    step_id: int,
    payload: schemas.AutoRunRequest,
    background_tasks: BackgroundTasks,
    db: Session,
    scoped: bool,
) -> schemas.AutoRunResponse:
    task_service.get_task_or_404(db, task_id)
    step = task_service.get_step_or_404(db, task_id, step_id)
    if step.status not in task_service.STARTABLE_STEP_STATUSES:
        return schemas.AutoRunResponse(task_id=task_id, started=False, step_id=step.id, message="Step is not startable")
    run_input = {**payload.input, "auto_run": True}
    if scoped:
        run_input["auto_run_start_step_id"] = step.id
    run = task_service.create_step_run(
        db,
        task_id,
        step.id,
        schemas.StepRunCreate(executor_type=payload.executor_type, executor_ref=payload.executor_ref, input=run_input),
    )
    if run.executor_type != "human":
        background_tasks.add_task(
            step_execution_service.execute_task_auto_run_background,
            task_id,
            step.id,
            run.id,
            run.executor_type,
            run.executor_ref,
            run_input,
        )
    return schemas.AutoRunResponse(task_id=task_id, started=True, step_id=step.id, run_id=run.id, message="Auto-run started")


@app.get("/tasks/{task_id}/steps/{step_id}/runs", response_model=list[schemas.StepRunRead])
def list_step_runs(task_id: int, step_id: int, db: Session = Depends(get_db)) -> list[schemas.StepRunRead]:
    return [task_service.run_to_schema(run) for run in task_service.list_step_runs(db, task_id, step_id)]


@app.post("/tasks/{task_id}/steps/{step_id}/runs/{run_id}/capability-invocations", response_model=schemas.CapabilityInvocationRead)
def create_capability_invocation(
    task_id: int,
    step_id: int,
    run_id: int,
    payload: schemas.CapabilityInvocationCreate,
    db: Session = Depends(get_db),
) -> schemas.CapabilityInvocationRead:
    invocation = task_service.create_capability_invocation(db, task_id, step_id, run_id, payload)
    return task_service.capability_invocation_to_schema(invocation)


@app.get("/tasks/{task_id}/steps/{step_id}/runs/{run_id}/capability-invocations", response_model=list[schemas.CapabilityInvocationRead])
def list_run_capability_invocations(task_id: int, step_id: int, run_id: int, db: Session = Depends(get_db)) -> list[schemas.CapabilityInvocationRead]:
    return [
        task_service.capability_invocation_to_schema(invocation)
        for invocation in task_service.list_run_capability_invocations(db, task_id, step_id, run_id)
    ]


@app.get("/tasks/{task_id}/capability-invocations", response_model=list[schemas.CapabilityInvocationRead])
def list_capability_invocations(task_id: int, db: Session = Depends(get_db)) -> list[schemas.CapabilityInvocationRead]:
    return [task_service.capability_invocation_to_schema(invocation) for invocation in task_service.list_capability_invocations(db, task_id)]


@app.patch("/tasks/{task_id}/capability-invocations/{invocation_id}", response_model=schemas.CapabilityInvocationRead)
def update_capability_invocation(
    task_id: int,
    invocation_id: int,
    payload: schemas.CapabilityInvocationUpdate,
    db: Session = Depends(get_db),
) -> schemas.CapabilityInvocationRead:
    invocation = task_service.update_capability_invocation(db, task_id, invocation_id, payload)
    return task_service.capability_invocation_to_schema(invocation)


@app.post("/tasks/{task_id}/steps/{step_id}/runs/{run_id}/submit", response_model=schemas.StepRunRead)
def submit_step_run(
    task_id: int,
    step_id: int,
    run_id: int,
    payload: schemas.StepRunSubmit,
    db: Session = Depends(get_db),
) -> schemas.StepRunRead:
    run = task_service.submit_step_run(db, task_id, step_id, run_id, payload)
    return task_service.run_to_schema(run)


@app.post("/tasks/{task_id}/steps/{step_id}/runs/{run_id}/review", response_model=schemas.ApprovalRead)
def review_step_run(
    task_id: int,
    step_id: int,
    run_id: int,
    payload: schemas.StepRunReview,
    db: Session = Depends(get_db),
) -> models.Approval:
    return task_service.review_step_run(db, task_id, step_id, run_id, payload)


@app.post("/tasks/{task_id}/steps/{step_id}/retry", response_model=schemas.StepRunRead)
def retry_step_run(
    task_id: int,
    step_id: int,
    payload: schemas.StepRunCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> schemas.StepRunRead:
    retry_input = {**payload.input, "auto_run": True, "auto_run_start_step_id": step_id}
    run = task_service.retry_step_run_in_place(db, task_id, step_id, payload.model_copy(update={"input": retry_input}))
    if run.executor_type != "human":
        background_tasks.add_task(
            step_execution_service.execute_task_auto_run_background,
            task_id,
            step_id,
            run.id,
            run.executor_type,
            run.executor_ref,
            retry_input,
        )
    return task_service.run_to_schema(run)


@app.post("/tasks/{task_id}/steps/{step_id}/rerun", response_model=schemas.StepRerunBranchResponse)
def rerun_step(
    task_id: int,
    step_id: int,
    payload: schemas.StepRerunBranchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> schemas.StepRerunBranchResponse:
    return task_service.rerun_step(db, task_id, step_id, payload)


@app.post("/internal/codex/runs/{run_id}/callback")
def codex_run_callback(
    run_id: int,
    payload: schemas.CodexRunCallback,
    authorization: str = Header(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return codex_execution_service.handle_codex_callback(
        db,
        run_id,
        payload,
        authorization,
        resume_auto_run=step_execution_service.execute_next_auto_run_step,
    )


@app.post("/internal/codex/tasks/{task_id}/hook")
def codex_task_hook_callback(
    task_id: int,
    payload: schemas.CodexTaskHookCallback,
    authorization: str = Header(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return codex_execution_service.handle_codex_task_hook(
        db,
        task_id,
        payload,
        authorization,
        resume_auto_run=step_execution_service.execute_next_auto_run_step,
    )


@app.get("/tasks/{task_id}/timeline", response_model=list[schemas.EventRead])
def list_timeline(task_id: int, db: Session = Depends(get_db)) -> list[schemas.EventRead]:
    return [task_service.event_to_schema(event) for event in task_service.list_timeline(db, task_id)]


@app.get("/tasks/{task_id}/artifacts", response_model=list[schemas.ArtifactRead])
def list_artifacts(task_id: int, db: Session = Depends(get_db)) -> list[schemas.ArtifactRead]:
    return [task_service.artifact_to_schema(artifact) for artifact in task_service.list_artifacts(db, task_id)]
