import base64
import hashlib
import hmac
import json
import re
import shlex
import subprocess
import threading
import time
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import settings
from ..db import SessionLocal
from . import task_service

SESSION_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
CODEX_STEP_PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "codex_step_prompt.md"
ResumeAutoRun = Callable[..., bool]


@lru_cache(maxsize=1)
def load_codex_step_prompt_template() -> Template:
    try:
        return Template(CODEX_STEP_PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Codex step prompt template not found: {CODEX_STEP_PROMPT_TEMPLATE_PATH}") from exc


def should_use_codex(task: models.Task) -> bool:
    return task.executor_mode == "codex"


def sanitize_session_name(value: str) -> str:
    sanitized = SESSION_SAFE.sub("-", value).strip("-")
    return sanitized[:80] or "longagent-codex"


def task_tmux_session_name(task_id: int) -> str:
    return sanitize_session_name(f"{settings.codex_tmux_session_prefix}-t{task_id}")


def resolve_workdir(project_path: str | None) -> Path:
    return Path(project_path or settings.codex_working_directory or Path.cwd()).expanduser().resolve()


def task_runtime_dir(task_id: int) -> Path:
    return Path(".long_agent_runtime") / "codex_tasks" / str(task_id)


def make_task_callback_token(task_id: int, expires_at: int | None = None) -> str:
    expiry = expires_at or 0
    body = f"{task_id}:{expiry}"
    signature = hmac.new(callback_secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{body}:{signature}".encode()).decode()


def verify_task_callback_token(token: str, task_id: int) -> None:
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        raw_task, raw_expiry, signature = decoded.rsplit(":", 2)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid Codex task callback token") from exc

    body = f"{raw_task}:{raw_expiry}"
    expected = hmac.new(callback_secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid Codex task callback token")
    if int(raw_task) != task_id:
        raise HTTPException(status_code=401, detail="Codex task callback token does not match task")

def callback_secret() -> str:
    if not settings.codex_callback_secret:
        raise HTTPException(status_code=503, detail="Codex callback secret is not configured")
    return settings.codex_callback_secret


def make_callback_token(task_id: int, step_id: int, run_id: int, attempt_number: int, expires_at: int | None = None) -> str:
    expiry = expires_at or int(time.time()) + settings.codex_timeout_seconds + 300
    body = f"{task_id}:{step_id}:{run_id}:{attempt_number}:{expiry}"
    signature = hmac.new(callback_secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{body}:{signature}".encode()).decode()


def verify_callback_token(token: str, task_id: int, step_id: int, run_id: int, attempt_number: int) -> None:
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        raw_task, raw_step, raw_run, raw_attempt, raw_expiry, signature = decoded.rsplit(":", 5)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid Codex callback token") from exc

    body = f"{raw_task}:{raw_step}:{raw_run}:{raw_attempt}:{raw_expiry}"
    expected = hmac.new(callback_secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid Codex callback token")
    if (int(raw_task), int(raw_step), int(raw_run), int(raw_attempt)) != (task_id, step_id, run_id, attempt_number):
        raise HTTPException(status_code=401, detail="Codex callback token does not match run")
    if int(raw_expiry) < int(time.time()):
        raise HTTPException(status_code=401, detail="Codex callback token expired")


def previous_steps_context(previous_step_summaries: list[dict[str, Any]] | None = None) -> str:
    if not previous_step_summaries:
        return "Completed previous steps count: 0\n- No previous approved steps."
    lines = [f"Completed previous steps count: {len(previous_step_summaries)}"]
    for item in previous_step_summaries:
        summary = item.get("summary") or "Completed."
        lines.append(f"- Completed Step {item.get('step_order')}: {item.get('title')}\n  Result: {summary}")
    return "\n".join(lines)


def build_prompt(
    task: models.Task,
    step: models.Step,
    run: models.StepRun,
    run_input: dict[str, Any],
    previous_step_summaries: list[dict[str, Any]] | None = None,
) -> str:
    return load_codex_step_prompt_template().substitute(
        task_title=task.title,
        constraints=task.constraints or "None",
        previous_steps_context=previous_steps_context(previous_step_summaries),
        step_order=step.step_order,
        step_title=step.title,
        step_objective=step.objective,
        run_input_json=json.dumps(run_input, ensure_ascii=False),
    )


def tmux_session_exists(session_name: str) -> bool:
    return subprocess.run(["tmux", "has-session", "-t", session_name], check=False).returncode == 0


def task_callback_script() -> str:
    return r'''#!/usr/bin/env bash
set -euo pipefail

payload_path="${1:-}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log_file="$script_dir/hook_invocations.log"
printf '%s Stop hook invoked for task %s payload=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${LONG_AGENT_TASK_ID:-unknown}" "$payload_path" >> "$log_file"

summary=""
if [ -n "$payload_path" ] && [ -f "$payload_path" ] && command -v jq >/dev/null 2>&1; then
  summary="$(jq -r '.last_assistant_message // empty' "$payload_path")"
else
  summary="$(cat)"
fi
trimmed="$(printf '%s' "$summary" | tr -d '[:space:]')"
status="completed"
error_json="null"
summary_arg=()
if [ -z "$trimmed" ]; then
  status="failed"
  error_json='"Codex hook did not receive a completion payload"'
  summary_arg=(--arg summary "")
else
  summary_arg=(--arg summary "${summary:0:4000}")
fi

json_payload="$(jq -n \
  --argjson task_id "$LONG_AGENT_TASK_ID" \
  --arg status "$status" \
  "${summary_arg[@]}" \
  --argjson error "$error_json" \
  '{
    task_id: $task_id,
    status: $status,
    summary: (if $summary == "" then null else $summary end),
    details: {hook_payload: $summary},
    error: $error
  }')"

if ! callback_response="$(curl -fsS \
  -X POST "$LONG_AGENT_CALLBACK_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LONG_AGENT_CALLBACK_TOKEN" \
  --data "$json_payload" 2>&1)"; then
  printf '%s Stop hook callback failed to %s: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$LONG_AGENT_CALLBACK_URL" "$callback_response" >> "$log_file"
  exit 1
fi

printf '%s Stop hook callback posted to %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$LONG_AGENT_CALLBACK_URL" >> "$log_file"
printf '{"continue": false}\n'
'''


def write_task_runtime_files(task_id: int) -> dict[str, Path | str]:
    run_dir = task_runtime_dir(task_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    callback_script_path = run_dir / "callback.sh"
    callback_script_path.write_text(task_callback_script(), encoding="utf-8")
    callback_script_path.chmod(0o700)
    return {
        "run_dir": run_dir,
        "callback_script_path": callback_script_path,
        "callback_url": f"{settings.codex_callback_base_url.rstrip('/')}/internal/codex/tasks/{task_id}/hook",
        "callback_token": make_task_callback_token(task_id),
    }


def task_session_env(task_id: int, workdir: Path, files: dict[str, Path | str]) -> dict[str, Path | str]:
    return {
        "CODEX_STOP_SCRIPT": files["callback_script_path"],
        "LONG_AGENT_TASK_ID": str(task_id),
        "LONG_AGENT_CALLBACK_URL": files["callback_url"],
        "LONG_AGENT_CALLBACK_TOKEN": files["callback_token"],
        "LONG_AGENT_XCODE_DERIVED_DATA_PATH": workdir / ".derivedData",
        "LONG_AGENT_XCODE_RESULT_BUNDLE_PATH": workdir / "TestResults" / "codex.xcresult",
    }


def build_task_session_command(task_id: int, workdir: Path, files: dict[str, Path | str]) -> str:
    session_env = task_session_env(task_id, workdir, files)
    env_prefix = " ".join(f"{key}={shlex.quote(str(value))}" for key, value in session_env.items())
    config_overrides = " ".join(f"-c {shlex.quote(f'env.{key}={json.dumps(str(value))}')}" for key, value in session_env.items())
    return (
        f"{env_prefix} {shlex.quote(settings.codex_command)} {config_overrides} --enable hooks --cd {shlex.quote(str(workdir))} "
        f"--sandbox {shlex.quote(settings.codex_sandbox)} --ask-for-approval {shlex.quote(settings.codex_approval_policy)}"
    )


def ensure_tmux_session(session_name: str, workdir: Path, task_id: int) -> bool:
    if tmux_session_exists(session_name):
        return False
    files = write_task_runtime_files(task_id)
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, "-c", str(workdir), "bash", "-lc", build_task_session_command(task_id, workdir, files)],
        check=True,
    )
    return True


def wait_for_codex_tui_ready(session_name: str) -> None:
    deadline = time.monotonic() + 10
    trust_prompt_answered = False
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-40"],
                check=True,
                capture_output=True,
                text=True,
            )
        except TypeError:
            return
        pane_text = result.stdout
        if not trust_prompt_answered and "Do you trust the contents of this directory?" in pane_text:
            subprocess.run(["tmux", "send-keys", "-t", session_name, "1"], check=True)
            time.sleep(0.1)
            subprocess.run(["tmux", "send-keys", "-t", session_name, "Enter"], check=True)
            trust_prompt_answered = True
            time.sleep(0.5)
            continue
        if "OpenAI Codex" in pane_text and "›" in pane_text:
            return
        time.sleep(0.5)


def kill_tmux_session(session_name: str) -> None:
    subprocess.run(["tmux", "kill-session", "-t", session_name], check=False)


def restart_tmux_session(session_name: str, workdir: Path, task_id: int) -> None:
    kill_tmux_session(session_name)
    ensure_tmux_session(session_name, workdir, task_id)
    try:
        wait_for_codex_tui_ready(session_name)
    except subprocess.CalledProcessError:
        kill_tmux_session(session_name)
        ensure_tmux_session(session_name, workdir, task_id)
        wait_for_codex_tui_ready(session_name)


def send_prompt_to_tmux(session_name: str, prompt: str) -> None:
    subprocess.run(["tmux", "send-keys", "-t", session_name, "-l", "--", prompt], check=True)
    time.sleep(0.1)
    subprocess.run(["tmux", "send-keys", "-t", session_name, "Enter"], check=True)


def start_task_codex_session(task_id: int, project_path: str | None) -> dict[str, str | bool]:
    if not settings.codex_enabled:
        raise HTTPException(status_code=503, detail="Codex executor is not enabled")
    workdir = resolve_workdir(project_path)
    session_name = task_tmux_session_name(task_id)
    started = ensure_tmux_session(session_name, workdir, task_id)
    if started:
        wait_for_codex_tui_ready(session_name)
    return {"tmux_session": session_name, "workdir": str(workdir), "started": started}


def initialize_task_codex_session(task_id: int, project_path: str | None) -> None:
    with SessionLocal() as db:
        task = task_service.get_task_or_404(db, task_id)
        session_name = task.codex_tmux_session or task_tmux_session_name(task_id)
        running_runs = (
            db.query(models.StepRun)
            .filter(models.StepRun.task_id == task_id, models.StepRun.executor_type == "codex", models.StepRun.status == "running")
            .all()
        )
        if running_runs:
            fail_running_codex_runs(db, task, running_runs, "codex_session_reinitialized", "Codex tmux session was reinitialized", session_name)

    metadata = start_task_codex_session(task_id, project_path)
    with SessionLocal() as db:
        task = task_service.get_task_or_404(db, task_id)
        task.codex_tmux_session = str(metadata["tmux_session"])
        task_service.record_event(db, task_id, "codex_session_started", metadata)
        task_service.commit_and_write_task_log(db, task_id)


def running_codex_run(db: Session, task_id: int) -> models.StepRun | None:
    return (
        db.query(models.StepRun)
        .filter(models.StepRun.task_id == task_id, models.StepRun.executor_type == "codex", models.StepRun.status == "running")
        .order_by(models.StepRun.started_at.desc(), models.StepRun.id.desc())
        .first()
    )


def capture_codex_pane(session_name: str, start_line: str = "-120") -> str | None:
    result = subprocess.run(["tmux", "capture-pane", "-t", session_name, "-p", "-S", start_line], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout


def codex_session_interrupted(session_name: str) -> bool:
    pane_text = capture_codex_pane(session_name, "-80")
    if pane_text is None:
        return True
    return "Conversation interrupted" in pane_text or "Model interrupted" in pane_text


def fail_running_codex_runs(db: Session, task: models.Task, running_runs: list[models.StepRun], event_type: str, reason: str, session_name: str) -> None:
    now = models.utcnow()
    failed_run_ids = []
    for run in running_runs:
        run.status = "failed"
        run.error = reason
        run.ended_at = now
        task_service.set_run_duration(run, now)
        failed_run_ids.append(run.id)
        step = db.get(models.Step, run.step_id)
        if step is not None and step.status == "running":
            step.status = "failed"
    task.status = "failed"
    task_service.record_event(db, task.id, event_type, {"tmux_session": session_name, "failed_run_ids": failed_run_ids, "reason": reason})
    task_service.recalculate_progress_event(db, task.id, event_type)
    task_service.commit_and_write_task_log(db, task.id)


def sync_missing_task_tmux_session(db: Session, task_id: int) -> None:
    task = task_service.get_task_or_404(db, task_id)
    if task.executor_mode != "codex" or task.status in {"completed", "failed", "archived", "cancelled"}:
        return
    running_runs = (
        db.query(models.StepRun)
        .filter(models.StepRun.task_id == task_id, models.StepRun.executor_type == "codex", models.StepRun.status == "running")
        .all()
    )
    if not running_runs:
        return
    session_name = task.codex_tmux_session or task_tmux_session_name(task_id)
    if not tmux_session_exists(session_name):
        fail_running_codex_runs(db, task, running_runs, "codex_session_missing", "Codex tmux session is not running", session_name)
        return
    if codex_session_interrupted(session_name):
        fail_running_codex_runs(db, task, running_runs, "codex_session_interrupted", "Codex tmux session was interrupted", session_name)
        return


def resume_running_codex_run(db: Session, task: models.Task, session_name: str) -> bool:
    run = running_codex_run(db, task.id)
    if run is None:
        return False
    step = db.get(models.Step, run.step_id)
    if step is None:
        return False
    run_input = task_service.decode_json(run.input) or {}
    previous_steps = [
        item
        for item in task_service.ordered_steps(db, task.id, active_only=True)
        if item.step_order < step.step_order
    ]
    from .step_execution_service import approved_step_summaries

    prompt = build_prompt(task, step, run, run_input, approved_step_summaries(db, previous_steps))
    send_prompt_to_tmux(session_name, prompt)
    return True


def keep_task_codex_session_alive(task_id: int) -> None:
    while True:
        with SessionLocal() as db:
            task = task_service.get_task_or_404(db, task_id)
            if task.executor_mode != "codex" or task.status in {"completed", "failed", "archived", "cancelled"}:
                return
            sync_missing_task_tmux_session(db, task_id)
            task = task_service.get_task_or_404(db, task_id)
            if task.executor_mode != "codex" or task.status in {"completed", "failed", "archived", "cancelled"}:
                return
            metadata = ensure_task_codex_session(task)
            if metadata.get("started"):
                task.codex_tmux_session = str(metadata["tmux_session"])
                resume_running_codex_run(db, task, str(metadata["tmux_session"]))
                task_service.record_event(db, task_id, "codex_session_restarted", metadata)
                task_service.commit_and_write_task_log(db, task_id)
        time.sleep(settings.codex_keepalive_interval_seconds)


def start_task_codex_keepalive(task_id: int, project_path: str | None) -> None:
    initialize_task_codex_session(task_id, project_path)
    thread = threading.Thread(target=keep_task_codex_session_alive, args=(task_id,), daemon=True)
    thread.start()


def ensure_task_codex_session(task: models.Task) -> dict[str, str | bool]:
    return start_task_codex_session(task.id, task.project_path)


def start_codex_tmux(
    task: models.Task,
    step: models.Step,
    run: models.StepRun,
    run_input: dict[str, Any],
    previous_step_summaries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not settings.codex_enabled:
        raise HTTPException(status_code=503, detail="Codex executor is not enabled")
    workdir = resolve_workdir(task.project_path)
    session_name = task.codex_tmux_session or task_tmux_session_name(task.id)
    started = ensure_tmux_session(session_name, workdir, task.id)
    try:
        if started:
            wait_for_codex_tui_ready(session_name)
        prompt = build_prompt(task, step, run, run_input, previous_step_summaries)
        send_prompt_to_tmux(session_name, prompt)
    except subprocess.CalledProcessError:
        restart_tmux_session(session_name, workdir, task.id)
        prompt = build_prompt(task, step, run, run_input, previous_step_summaries)
        send_prompt_to_tmux(session_name, prompt)
    return {"tmux_session": session_name, "workdir": str(workdir)}


def analyze_codex_result(payload: schemas.CodexRunCallback) -> tuple[bool, str, dict[str, Any]]:
    output = {
        "summary": payload.summary or "",
        "details": payload.details,
        "artifacts": [artifact.model_dump() for artifact in payload.artifacts],
        "executor": "codex",
    }
    if payload.status == "failed":
        return False, payload.error or "Codex reported failure", output
    if not payload.summary or not payload.summary.strip():
        return False, "Codex result did not include a summary", output
    return True, "Codex result accepted", output


def current_running_codex_run(db: Session, task_id: int) -> models.StepRun:
    run = (
        db.query(models.StepRun)
        .filter(models.StepRun.task_id == task_id, models.StepRun.executor_type == "codex", models.StepRun.status == "running")
        .order_by(models.StepRun.started_at.desc(), models.StepRun.id.desc())
        .first()
    )
    if run is None:
        raise HTTPException(status_code=409, detail="No running Codex step run for task")
    return run


def codex_task_payload_to_run_payload(run: models.StepRun, payload: schemas.CodexTaskHookCallback) -> schemas.CodexRunCallback:
    return schemas.CodexRunCallback(
        task_id=payload.task_id,
        step_id=run.step_id,
        run_id=run.id,
        attempt_number=run.attempt_number,
        status=payload.status,
        summary=payload.summary,
        details=payload.details,
        artifacts=payload.artifacts,
        error=payload.error,
    )


def handle_codex_task_hook(
    db: Session,
    task_id: int,
    payload: schemas.CodexTaskHookCallback,
    authorization: str,
    resume_auto_run: ResumeAutoRun | None = None,
) -> dict[str, Any]:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Codex task callback token")
    verify_task_callback_token(authorization.removeprefix("Bearer ").strip(), task_id)
    if payload.task_id != task_id:
        raise HTTPException(status_code=401, detail="Codex task callback token does not match payload")
    run = current_running_codex_run(db, task_id)
    run_payload = codex_task_payload_to_run_payload(run, payload)
    return handle_codex_callback(db, run.id, run_payload, authorization=f"Bearer {make_callback_token(task_id, run.step_id, run.id, run.attempt_number)}", resume_auto_run=resume_auto_run)


def handle_codex_callback(
    db: Session,
    run_id: int,
    payload: schemas.CodexRunCallback,
    authorization: str,
    resume_auto_run: ResumeAutoRun | None = None,
) -> dict[str, Any]:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Codex callback token")
    verify_callback_token(authorization.removeprefix("Bearer ").strip(), payload.task_id, payload.step_id, run_id, payload.attempt_number)
    run = task_service.get_run_or_404(db, payload.task_id, payload.step_id, run_id)
    if run.attempt_number != payload.attempt_number:
        raise HTTPException(status_code=409, detail="Codex callback attempt does not match run")
    if run.status != "running":
        raise HTTPException(status_code=409, detail="Codex callback is stale")

    run_input = task_service.decode_json(run.input) or {}
    complete, reason, output = analyze_codex_result(payload)
    if complete:
        task_service.complete_step_run_automatically(db, payload.task_id, payload.step_id, run_id, output)
        resumed = bool(run_input.get("auto_run") and resume_auto_run and resume_auto_run(payload.task_id, run_input=run_input, current_step_id=payload.step_id))
        return {"accepted": True, "retry": False, "resumed": resumed, "reason": reason}

    max_attempts = settings.codex_max_attempts
    if payload.attempt_number >= max_attempts:
        task_service.fail_step_run(db, payload.task_id, payload.step_id, run_id, reason)
        return {"accepted": False, "retry": False, "reason": reason}

    task_service.mark_step_run_incomplete_for_retry(db, payload.task_id, payload.step_id, run_id, output, reason)
    retry_input = {**run_input, "executor_hint": "codex", "retry_reason": reason}
    retry_run = task_service.retry_step_run_in_place(db, payload.task_id, payload.step_id, schemas.StepRunCreate(executor_type="codex", input=retry_input))
    db.refresh(retry_run)
    task = task_service.get_task_or_404(db, payload.task_id)
    step = task_service.get_step_or_404(db, payload.task_id, payload.step_id)
    metadata = start_codex_tmux(task, step, retry_run, retry_input)
    retry_run.output = task_service.encode_json({"executor": "codex", "status": "launched", **metadata})
    task_service.record_event(db, payload.task_id, "codex_run_launched", metadata, step_id=payload.step_id, run_id=retry_run.id)
    task_service.commit_and_write_task_log(db, payload.task_id)
    return {"accepted": False, "retry": True, "run_id": retry_run.id, "reason": reason}
