from pathlib import Path

from app.services import task_service


def create_task(client):
    response = client.post(
        "/tasks",
        json={
            "title": "Logged task",
            "goal": "Capture every execution detail",
            "constraints": "Do not leak tokens",
            "initial_message": "Initial request with api_key=secret-key",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def generate_plan(client, task_id):
    response = client.post(
        f"/tasks/{task_id}/generate-plan",
        json={
            "reason": "Create logged plan",
            "steps": [
                {"title": "Collect data", "objective": "Gather inputs"},
                {"title": "Write summary", "objective": "Summarize outputs"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def approve_plan(client, task_id):
    response = client.post(f"/tasks/{task_id}/approve-plan", json={"decision": "approved", "comment": "Plan approved"})
    assert response.status_code == 200, response.text
    return response.json()


def create_run(client, task_id, step_id):
    response = client.post(
        f"/tasks/{task_id}/steps/{step_id}/runs",
        json={"executor_type": "human", "input": {"note": "attempt", "token": "secret-token"}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def submit_run(client, task_id, step_id, run_id):
    response = client.post(
        f"/tasks/{task_id}/steps/{step_id}/runs/{run_id}/submit",
        json={"output": {"summary": "ready", "password": "secret-password"}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def review_run(client, task_id, step_id, run_id):
    response = client.post(
        f"/tasks/{task_id}/steps/{step_id}/runs/{run_id}/review",
        json={"decision": "approved", "comment": "Looks good"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_capability_invocation(client, task_id, step_id, run_id):
    response = client.post(
        f"/tasks/{task_id}/steps/{step_id}/runs/{run_id}/capability-invocations",
        json={"invoked_by_type": "human", "capability_id": "generate_report", "input": {"topic": "logs", "api_key": "secret-key"}},
    )
    assert response.status_code == 200, response.text
    invocation = response.json()
    response = client.patch(
        f"/tasks/{task_id}/capability-invocations/{invocation['id']}",
        json={
            "status": "succeeded",
            "output": {"summary": "report complete", "secret": "secret-value"},
            "duration_ms": 123,
            "artifacts": [{"type": "file", "name": "report.md", "uri": "file://report.md", "metadata": {"token": "artifact-token"}}],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def build_logged_task(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]
    run = create_run(client, task["id"], step["id"])
    create_capability_invocation(client, task["id"], step["id"], run["id"])
    submit_run(client, task["id"], step["id"], run["id"])
    review_run(client, task["id"], step["id"], run["id"])
    return task, step, run


def read_task_log(task_id):
    text_path = Path(task_service.task_log_path(task_id))
    assert text_path.exists()
    assert not text_path.with_suffix(".json").exists()
    return text_path.read_text(encoding="utf-8")


def test_task_log_files_include_execution_sequence_capabilities_artifacts_and_text(client, tmp_path, monkeypatch):
    monkeypatch.setattr(task_service, "TASK_LOG_DIR", tmp_path / "task_logs")
    task, step, run = build_logged_task(client)

    log_text = read_task_log(task["id"])

    assert task["log_path"] == str(tmp_path / "task_logs" / f"task_{task['id']}.log")
    assert log_text.startswith("Execution log: Logged task")
    assert "Collect data" in log_text
    assert "attempt" in log_text
    assert "event=task_snapshot" in log_text
    assert "event=task_message" in log_text
    assert "event=task_revision" in log_text
    assert "event=step_snapshot" in log_text
    assert "event=run_snapshot" in log_text
    assert "event=approval_snapshot" in log_text
    assert "event=capability_invocation_snapshot" in log_text
    assert "event=artifact_snapshot" in log_text
    assert "event=step_run_started" in log_text
    assert "event=step_run_submitted" in log_text
    assert "event=step_run_reviewed" in log_text
    assert "event=capability_invocation_recorded" in log_text
    assert "event=capability_invocation_updated" in log_text
    assert "event=artifact_created" in log_text
    assert '"token": "[REDACTED]"' in log_text
    assert '"password": "[REDACTED]"' in log_text
    assert '"api_key": "[REDACTED]"' in log_text
    assert '"secret": "[REDACTED]"' in log_text
    assert "duration_ms=123" in log_text
    assert "```" not in log_text
    assert "secret-token" not in log_text
    assert "secret-password" not in log_text
    assert "secret-key" not in log_text
    assert "artifact-token" not in log_text


def test_task_log_files_are_refreshed_after_later_task_mutations(client, tmp_path, monkeypatch):
    monkeypatch.setattr(task_service, "TASK_LOG_DIR", tmp_path / "task_logs")
    task = create_task(client)
    log_text = read_task_log(task["id"])
    assert "Plan revision" not in log_text

    generate_plan(client, task["id"])
    log_text = read_task_log(task["id"])

    assert "Plan revision" in log_text
    assert "event=task_revision" in log_text

def test_auto_plan_task_log_includes_llm_call_details(client, tmp_path, monkeypatch):
    monkeypatch.setattr(task_service, "TASK_LOG_DIR", tmp_path / "task_logs")
    task = create_task(client)

    client.patch("/settings/planner-prompt", json={"prompt": "Runtime planner prompt"})

    def fake_generate_plan_steps(_task, _messages, _system_prompt, _instructions=None):
        return [task_service.schemas.PlanStepCreate(title="Auto step", objective="Generated by fake planner")]

    monkeypatch.setattr(task_service, "generate_plan_steps", fake_generate_plan_steps)
    response = client.post(
        f"/tasks/{task['id']}/generate-plan",
        json={"generation_mode": "auto", "reason": "LLM decomposition", "instructions": "Prefer one stage"},
    )
    assert response.status_code == 200, response.text

    log_text = read_task_log(task["id"])
    assert "event=llm_call" in log_text
    assert '"purpose": "plan_generation"' in log_text
    assert '"provider": "openai_compatible"' in log_text
    assert '"role": "system"' in log_text
    assert "Runtime planner prompt" in log_text
    assert "Extra instructions: Prefer one stage" in log_text
    assert "llm call" in log_text.lower()


def test_task_log_route_is_not_exposed(client):
    task = create_task(client)

    response = client.get(f"/tasks/{task['id']}/logs")

    assert response.status_code == 404
