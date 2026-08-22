import pytest
from pathlib import Path

from app.services import codex_execution_service


def create_task(client):
    response = client.post(
        "/tasks",
        json={
            "title": "Long investigation",
            "goal": "Manage a long-running workflow",
            "constraints": "Keep scope defensive",
            "initial_message": "Initial intake",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def generate_plan(client, task_id):
    response = client.post(
        f"/tasks/{task_id}/generate-plan",
        json={
            "reason": "Initial decomposition",
            "steps": [
                {"title": "Step one", "objective": "First objective"},
                {"title": "Step two", "objective": "Second objective"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def approve_plan(client, task_id):
    response = client.post(f"/tasks/{task_id}/approve-plan", json={"decision": "approved"})
    assert response.status_code == 200, response.text
    return response.json()


def create_run(client, task_id, step_id, executor_type="human"):
    response = client.post(
        f"/tasks/{task_id}/steps/{step_id}/runs",
        json={"executor_type": executor_type, "input": {"note": "attempt"}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def submit_run(client, task_id, step_id, run_id):
    response = client.post(
        f"/tasks/{task_id}/steps/{step_id}/runs/{run_id}/submit",
        json={"output": {"summary": "ready"}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_create_task_status_intake_and_message_updates_constraints(client):
    task = create_task(client)
    assert task["status"] == "intake"
    assert task["constraints"] == "Keep scope defensive"

    response = client.post(
        f"/tasks/{task['id']}/messages",
        json={"message": "Add constraint", "constraints": "No external execution"},
    )
    assert response.status_code == 200, response.text

    detail = client.get(f"/tasks/{task['id']}").json()
    assert detail["task"]["constraints"] == "No external execution"
    assert detail["current_pointer"] == {
        "task_id": task["id"],
        "step_id": None,
        "run_id": None,
        "capability_invocation_id": None,
    }
    assert detail["next_actions"][0]["action_type"] == "generate_plan"
    assert detail["next_actions"][0]["target"]["task_id"] == task["id"]


def test_generate_and_approve_plan_then_dynamic_step(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    assert detail["task"]["status"] == "waiting_plan_review"
    assert len(detail["steps"]) == 2
    first_step, second_step = detail["steps"]
    assert first_step["previous_step_ids"] == []
    assert first_step["next_step_ids"] == [second_step["id"]]
    assert second_step["previous_step_ids"] == [first_step["id"]]
    assert second_step["next_step_ids"] == []
    assert detail["next_actions"][0]["action_type"] == "approve_plan"

    detail = approve_plan(client, task["id"])
    assert detail["task"]["status"] == "planned"

    response = client.post(
        f"/tasks/{task['id']}/steps",
        json={"title": "Dynamic step", "objective": "Added during execution"},
    )
    assert response.status_code == 200, response.text
    steps = client.get(f"/tasks/{task['id']}/steps").json()
    assert len(steps) == 3
    assert steps[-1]["title"] == "Dynamic step"
    assert steps[-2]["next_step_ids"] == [steps[-1]["id"]]
    assert steps[-1]["previous_step_ids"] == [steps[-2]["id"]]



def test_insert_step_after_rewires_explicit_graph(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    first_step, second_step = detail["steps"]

    response = client.post(
        f"/tasks/{task['id']}/steps",
        json={"title": "Inserted step", "objective": "Middle objective", "insert_mode": "insert_after_step", "target_step_id": first_step["id"]},
    )
    assert response.status_code == 200, response.text
    inserted = response.json()

    steps = client.get(f"/tasks/{task['id']}/steps").json()
    first_after = next(step for step in steps if step["id"] == first_step["id"])
    second_after = next(step for step in steps if step["id"] == second_step["id"])
    inserted_after = next(step for step in steps if step["id"] == inserted["id"])
    assert first_after["next_step_ids"] == [inserted["id"]]
    assert inserted_after["previous_step_ids"] == [first_step["id"]]
    assert inserted_after["next_step_ids"] == [second_step["id"]]
    assert second_after["previous_step_ids"] == [inserted["id"]]


def test_update_step_content_requires_no_run_history(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    first_step = detail["steps"][0]

    response = client.patch(
        f"/tasks/{task['id']}/steps/{first_step['id']}",
        json={"title": "Edited title", "objective": "Edited objective"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Edited title"
    assert response.json()["objective"] == "Edited objective"

    run = create_run(client, task["id"], first_step["id"], "human")
    response = client.patch(
        f"/tasks/{task['id']}/steps/{first_step['id']}",
        json={"objective": "Edited after run"},
    )
    assert response.status_code == 400
    assert "run history" in response.text
    assert run["status"] == "running"


def test_supersede_step_rewires_explicit_graph(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    first_step, second_step = detail["steps"]

    response = client.post(
        f"/tasks/{task['id']}/steps/{first_step['id']}/supersede",
        json={"new_step": {"title": "Replacement", "objective": "Replacement objective"}, "reason": "Better plan"},
    )
    assert response.status_code == 200, response.text
    replacement = response.json()

    steps = client.get(f"/tasks/{task['id']}/steps").json()
    old_step = next(step for step in steps if step["id"] == first_step["id"])
    replacement_step = next(step for step in steps if step["id"] == replacement["id"])
    second_after = next(step for step in steps if step["id"] == second_step["id"])
    assert old_step["previous_step_ids"] == []
    assert old_step["next_step_ids"] == []
    assert replacement_step["previous_step_ids"] == []
    assert replacement_step["next_step_ids"] == [second_step["id"]]
    assert second_after["previous_step_ids"] == [replacement["id"]]


def test_codex_task_creates_missing_project_path(client, monkeypatch, tmp_path):
    monkeypatch.setattr(codex_execution_service.settings, "codex_enabled", True)
    monkeypatch.setattr(codex_execution_service.settings, "codex_callback_secret", "secret")
    monkeypatch.setattr(codex_execution_service, "start_task_codex_keepalive", lambda task_id, project_path: None)
    project_path = tmp_path / "new-codex-project"

    response = client.post(
        "/tasks",
        json={"title": "Codex task", "goal": "Use Codex", "executor_mode": "codex", "project_path": str(project_path)},
    )

    assert response.status_code == 200, response.text
    assert project_path.is_dir()
    assert response.json()["project_path"] == str(project_path)


def test_codex_task_rejects_project_path_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr(codex_execution_service.settings, "codex_enabled", True)
    monkeypatch.setattr(codex_execution_service.settings, "codex_callback_secret", "secret")
    project_path = tmp_path / "not-a-directory"
    project_path.write_text("not a directory", encoding="utf-8")

    response = client.post(
        "/tasks",
        json={"title": "Codex task", "goal": "Use Codex", "executor_mode": "codex", "project_path": str(project_path)},
    )

    assert response.status_code == 422


def test_codex_task_starts_tmux_session_on_create(client, monkeypatch, tmp_path):
    monkeypatch.setattr(codex_execution_service.settings, "codex_enabled", True)
    monkeypatch.setattr(codex_execution_service.settings, "codex_callback_secret", "secret")
    calls = []

    def fake_run(args, check):
        calls.append(args)
        class Result:
            returncode = 1 if args[:3] == ["tmux", "has-session", "-t"] else 0
        return Result()

    def fake_start_task_codex_keepalive(task_id, project_path):
        codex_execution_service.initialize_task_codex_session(task_id, project_path)

    monkeypatch.setattr(codex_execution_service.subprocess, "run", fake_run)
    monkeypatch.setattr(codex_execution_service, "start_task_codex_keepalive", fake_start_task_codex_keepalive)

    response = client.post(
        "/tasks",
        json={"title": "Codex task", "goal": "Use Codex", "executor_mode": "codex", "project_path": str(tmp_path)},
    )
    assert response.status_code == 200, response.text

    task = client.get(f"/tasks/{response.json()['id']}").json()["task"]
    assert task["codex_tmux_session"] == f"longagent-t{task['id']}"
    new_session = next(args for args in calls if args[:2] == ["tmux", "new-session"])
    assert new_session[:8] == [
        "tmux",
        "new-session",
        "-d",
        "-s",
        task["codex_tmux_session"],
        "-c",
        str(tmp_path),
        "bash",
    ]
    command = new_session[-1]
    assert "CODEX_HOME=" not in command
    assert "CODEX_STOP_SCRIPT=" in command
    assert "-c 'env.CODEX_STOP_SCRIPT=" in command
    assert "LONG_AGENT_TASK_ID=" in command
    assert "-c 'env.LONG_AGENT_TASK_ID=" in command
    assert "LONG_AGENT_CALLBACK_URL=" in command
    assert "-c 'env.LONG_AGENT_CALLBACK_URL=" in command
    assert "LONG_AGENT_CALLBACK_TOKEN=" in command
    assert "-c 'env.LONG_AGENT_CALLBACK_TOKEN=" in command
    assert "LONG_AGENT_XCODE_DERIVED_DATA_PATH=" in command
    assert "-c 'env.LONG_AGENT_XCODE_DERIVED_DATA_PATH=" in command
    assert "LONG_AGENT_XCODE_RESULT_BUNDLE_PATH=" in command
    assert "-c 'env.LONG_AGENT_XCODE_RESULT_BUNDLE_PATH=" in command
    assert "--enable hooks" in command
    assert f"--cd {tmp_path}" in command
    assert "--sandbox danger-full-access --ask-for-approval never" in command


def test_codex_keepalive_restarts_missing_tmux_session_and_resends_running_run(client, monkeypatch, tmp_path):
    monkeypatch.setattr(codex_execution_service.settings, "codex_enabled", True)
    monkeypatch.setattr(codex_execution_service.settings, "codex_callback_secret", "secret")
    calls = []

    capture_count = {"value": 0}

    def fake_run(args, check, **_kwargs):
        calls.append(args)
        class Result:
            returncode = 0
            stdout = "OpenAI Codex\n›"
        if args[:3] == ["tmux", "has-session", "-t"]:
            Result.returncode = 1 if len(calls) > 1 else 0
        if args[:2] == ["tmux", "capture-pane"]:
            capture_count["value"] += 1
            Result.stdout = (
                "Do you trust the contents of this directory?\n› 1. Yes, continue\n  2. No, quit"
                if capture_count["value"] == 1
                else "OpenAI Codex\n›"
            )
        return Result()

    def fake_start_task_codex_keepalive(task_id, project_path):
        codex_execution_service.initialize_task_codex_session(task_id, project_path)

    def fake_sleep(seconds):
        if seconds == codex_execution_service.settings.codex_keepalive_interval_seconds:
            raise StopIteration

    monkeypatch.setattr(codex_execution_service.subprocess, "run", fake_run)
    monkeypatch.setattr(codex_execution_service, "start_task_codex_keepalive", fake_start_task_codex_keepalive)
    task = client.post(
        "/tasks",
        json={"title": "Codex task", "goal": "Use Codex", "executor_mode": "codex", "project_path": str(tmp_path)},
    ).json()
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]
    create_run(client, task["id"], step["id"], "agent")
    monkeypatch.setattr(codex_execution_service.time, "sleep", fake_sleep)
    capture_count["value"] = 0
    calls.clear()

    with pytest.raises(StopIteration):
        codex_execution_service.keep_task_codex_session_alive(task["id"])

    session_name = f"longagent-t{task['id']}"
    new_session = next(args for args in calls if args[:2] == ["tmux", "new-session"])
    assert new_session[:8] == [
        "tmux",
        "new-session",
        "-d",
        "-s",
        session_name,
        "-c",
        str(tmp_path),
        "bash",
    ]
    command = new_session[-1]
    assert "CODEX_HOME=" not in command
    assert "CODEX_STOP_SCRIPT=" in command
    assert "-c 'env.CODEX_STOP_SCRIPT=" in command
    assert "LONG_AGENT_TASK_ID=" in command
    assert "-c 'env.LONG_AGENT_TASK_ID=" in command
    assert "LONG_AGENT_CALLBACK_URL=" in command
    assert "-c 'env.LONG_AGENT_CALLBACK_URL=" in command
    assert "LONG_AGENT_CALLBACK_TOKEN=" in command
    assert "-c 'env.LONG_AGENT_CALLBACK_TOKEN=" in command
    assert "LONG_AGENT_XCODE_DERIVED_DATA_PATH=" in command
    assert "-c 'env.LONG_AGENT_XCODE_DERIVED_DATA_PATH=" in command
    assert "LONG_AGENT_XCODE_RESULT_BUNDLE_PATH=" in command
    assert "-c 'env.LONG_AGENT_XCODE_RESULT_BUNDLE_PATH=" in command
    assert "--enable hooks" in command
    assert f"--cd {tmp_path}" in command
    assert "--sandbox danger-full-access --ask-for-approval never" in command
    send_keys = [args for args in calls if args[:2] == ["tmux", "send-keys"]]
    prompt_send = next(args for args in send_keys if args[:6] == ["tmux", "send-keys", "-t", session_name, "-l", "--"])
    assert "Step 1: Step one" in prompt_send[-1]
    assert send_keys[-1] == ["tmux", "send-keys", "-t", session_name, "Enter"]


def test_close_task_cancels_running_run_and_records_event(client, monkeypatch):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]
    run = create_run(client, task["id"], step["id"], "human")

    killed = []
    monkeypatch.setattr(codex_execution_service, "kill_tmux_session", killed.append)
    response = client.post(f"/tasks/{task['id']}/close", json={"reason": "No longer needed", "actor_id": "tester"})

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["task"]["status"] == "cancelled"
    assert killed == []
    runs = client.get(f"/tasks/{task['id']}/steps/{step['id']}/runs").json()
    assert runs[0]["id"] == run["id"]
    assert runs[0]["status"] == "cancelled"
    assert runs[0]["ended_at"] is not None
    assert runs[0]["duration_ms"] is not None
    assert runs[0]["duration_ms"] >= 0
    assert runs[0]["error"] == "No longer needed"
    timeline = client.get(f"/tasks/{task['id']}/timeline").json()
    close_event = next(event for event in timeline if event["event_type"] == "task_closed")
    assert close_event["payload"]["cancelled_run_ids"] == [run["id"]]
    assert close_event["payload"]["reason"] == "No longer needed"


def test_close_codex_task_kills_tmux_session_and_is_idempotent(client, monkeypatch, tmp_path):
    monkeypatch.setattr(codex_execution_service.settings, "codex_enabled", True)
    monkeypatch.setattr(codex_execution_service.settings, "codex_callback_secret", "secret")
    monkeypatch.setattr(codex_execution_service, "start_task_codex_keepalive", lambda task_id, project_path: None)
    monkeypatch.setattr(codex_execution_service, "wait_for_codex_tui_ready", lambda session_name: None)
    monkeypatch.setattr(codex_execution_service.subprocess, "run", lambda args, check, **_kwargs: type("Result", (), {"returncode": 1 if args[:3] == ["tmux", "has-session", "-t"] else 0, "stdout": "OpenAI Codex\n›"})())
    killed = []
    monkeypatch.setattr(codex_execution_service, "kill_tmux_session", killed.append)

    task = client.post(
        "/tasks",
        json={"title": "Codex task", "goal": "Use Codex", "executor_mode": "codex", "project_path": str(tmp_path)},
    ).json()
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    create_run(client, task["id"], detail["steps"][0]["id"], "agent")
    first = client.post(f"/tasks/{task['id']}/close", json={"reason": "Stop Codex"})
    second = client.post(f"/tasks/{task['id']}/close", json={"reason": "Stop again"})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["task"]["status"] == "cancelled"
    assert second.json()["task"]["status"] == "cancelled"
    assert killed == [f"longagent-t{task['id']}"]



def test_codex_task_detail_marks_running_run_failed_when_tmux_session_is_missing(client, monkeypatch, tmp_path):
    monkeypatch.setattr(codex_execution_service.settings, "codex_enabled", True)
    monkeypatch.setattr(codex_execution_service.settings, "codex_callback_secret", "secret")
    monkeypatch.setattr(codex_execution_service, "start_task_codex_keepalive", lambda task_id, project_path: None)
    monkeypatch.setattr(codex_execution_service, "start_codex_tmux", lambda task, step, run, run_input, previous_step_summaries=None: {"tmux_session": f"longagent-t{task.id}", "workdir": str(tmp_path)})
    monkeypatch.setattr(codex_execution_service, "tmux_session_exists", lambda session_name: False)

    task = client.post(
        "/tasks",
        json={"title": "Codex task", "goal": "Use Codex", "executor_mode": "codex", "project_path": str(tmp_path)},
    ).json()
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]
    run = create_run(client, task["id"], step["id"], "agent")

    detail = client.get(f"/tasks/{task['id']}").json()
    runs = client.get(f"/tasks/{task['id']}/steps/{step['id']}/runs").json()
    failed_step = next(item for item in detail["steps"] if item["id"] == step["id"])
    assert detail["task"]["status"] == "failed"
    assert failed_step["status"] == "failed"
    assert runs[0]["id"] == run["id"]
    assert runs[0]["status"] == "failed"
    assert runs[0]["error"] == "Codex tmux session is not running"
    timeline = client.get(f"/tasks/{task['id']}/timeline").json()
    assert "codex_session_missing" in [event["event_type"] for event in timeline]



def test_codex_task_detail_marks_running_run_failed_when_tmux_session_is_interrupted(client, monkeypatch, tmp_path):
    monkeypatch.setattr(codex_execution_service.settings, "codex_enabled", True)
    monkeypatch.setattr(codex_execution_service.settings, "codex_callback_secret", "secret")
    monkeypatch.setattr(codex_execution_service, "start_task_codex_keepalive", lambda task_id, project_path: None)
    monkeypatch.setattr(codex_execution_service, "start_codex_tmux", lambda task, step, run, run_input, previous_step_summaries=None: {"tmux_session": f"longagent-t{task.id}", "workdir": str(tmp_path)})
    monkeypatch.setattr(codex_execution_service, "tmux_session_exists", lambda session_name: True)
    monkeypatch.setattr(codex_execution_service, "codex_session_interrupted", lambda session_name: True)

    task = client.post(
        "/tasks",
        json={"title": "Codex task", "goal": "Use Codex", "executor_mode": "codex", "project_path": str(tmp_path)},
    ).json()
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]
    run = create_run(client, task["id"], step["id"], "agent")

    detail = client.get(f"/tasks/{task['id']}").json()
    runs = client.get(f"/tasks/{task['id']}/steps/{step['id']}/runs").json()
    failed_step = next(item for item in detail["steps"] if item["id"] == step["id"])
    assert detail["task"]["status"] == "failed"
    assert failed_step["status"] == "failed"
    assert runs[0]["id"] == run["id"]
    assert runs[0]["status"] == "failed"
    assert runs[0]["error"] == "Codex tmux session was interrupted"
    timeline = client.get(f"/tasks/{task['id']}/timeline").json()
    assert "codex_session_interrupted" in [event["event_type"] for event in timeline]



def test_generate_plan_replaces_unapproved_existing_plan(client):
    task = create_task(client)
    generate_plan(client, task["id"])

    replaced = client.post(
        f"/tasks/{task['id']}/generate-plan",
        json={
            "reason": "Replace mistaken manual plan",
            "steps": [
                {"title": "Detailed step one", "objective": "First replacement objective"},
                {"title": "Detailed step two", "objective": "Second replacement objective"},
                {"title": "Detailed step three", "objective": "Third replacement objective"},
            ],
        },
    )
    assert replaced.status_code == 200, replaced.text
    detail = replaced.json()
    assert detail["task"]["status"] == "waiting_plan_review"
    assert [step["title"] for step in detail["steps"]] == ["Detailed step one", "Detailed step two", "Detailed step three"]


def test_generate_plan_rejects_after_approval(client):
    task = create_task(client)
    generate_plan(client, task["id"])
    approve_plan(client, task["id"])

    repeated_generation = client.post(
        f"/tasks/{task['id']}/generate-plan",
        json={"steps": [{"title": "Another", "objective": "Should be rejected"}]},
    )
    assert repeated_generation.status_code == 400


def test_approve_plan_requires_waiting_review_and_steps(client):
    task = create_task(client)

    early_approval = client.post(f"/tasks/{task['id']}/approve-plan", json={"decision": "approved"})
    assert early_approval.status_code == 400

    generate_plan(client, task["id"])
    approved = approve_plan(client, task["id"])
    assert approved["task"]["status"] == "planned"

    repeated_approval = client.post(f"/tasks/{task['id']}/approve-plan", json={"decision": "approved"})
    assert repeated_approval.status_code == 400


def test_run_submit_approve_sets_status_and_progress(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]

    run = create_run(client, task["id"], step["id"], "human")
    assert run["attempt_number"] == 1
    assert run["status"] == "running"
    assert run["duration_ms"] is not None
    assert run["duration_ms"] >= 0

    detail = client.get(f"/tasks/{task['id']}").json()
    assert detail["task"]["status"] == "running"
    assert detail["current_pointer"]["step_id"] == step["id"]
    assert detail["current_pointer"]["run_id"] == run["id"]

    submitted = submit_run(client, task["id"], step["id"], run["id"])
    assert submitted["status"] == "submitted"
    assert submitted["duration_ms"] is not None
    assert submitted["duration_ms"] >= 0

    detail = client.get(f"/tasks/{task['id']}").json()
    assert detail["task"]["status"] == "waiting_review"
    action = detail["next_actions"][0]
    assert action["action_type"] == "review_step_run"
    assert action["target"] == {"task_id": task["id"], "step_id": step["id"], "run_id": run["id"]}

    approval = client.post(
        f"/tasks/{task['id']}/steps/{step['id']}/runs/{run['id']}/review",
        json={"decision": "approved"},
    ).json()
    assert approval["decision"] == "approved"

    steps = client.get(f"/tasks/{task['id']}/steps").json()
    approved_step = next(item for item in steps if item["id"] == step["id"])
    assert approved_step["status"] == "approved"
    assert approved_step["approved_run_id"] == run["id"]

    runs = client.get(f"/tasks/{task['id']}/steps/{step['id']}/runs").json()
    assert runs[0]["status"] == "accepted"

    detail = client.get(f"/tasks/{task['id']}").json()
    assert detail["task"]["status"] == "planned"
    assert detail["progress"]["active_steps_total"] == 2
    assert detail["progress"]["approved_or_skipped_active_steps"] == 1
    assert detail["progress"]["progress_percent"] == 50.0
    assert detail["progress"]["consumed_ms"] >= runs[0]["duration_ms"]
    approved_step_detail = next(item for item in detail["steps"] if item["id"] == step["id"])
    assert approved_step_detail["consumed_ms"] >= runs[0]["duration_ms"]


def test_submit_rejects_non_running_run(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]
    run = create_run(client, task["id"], step["id"], "human")
    submit_run(client, task["id"], step["id"], run["id"])

    response = client.post(f"/tasks/{task['id']}/steps/{step['id']}/runs/{run['id']}/submit", json={"output": {"again": True}})

    assert response.status_code == 400
    assert response.json()["detail"] == "Only running runs can be submitted"


def test_review_rejects_non_submitted_run(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]
    run = create_run(client, task["id"], step["id"], "human")

    response = client.post(f"/tasks/{task['id']}/steps/{step['id']}/runs/{run['id']}/review", json={"decision": "approved"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Only submitted runs can be reviewed"


def test_draft_plan_steps_can_be_edited_but_not_run_before_approval(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    first_step = detail["steps"][0]

    edit_response = client.patch(
        f"/tasks/{task['id']}/steps/{first_step['id']}",
        json={"title": "Edited draft title", "objective": "Edited draft objective"},
    )
    assert edit_response.status_code == 200, edit_response.text
    assert edit_response.json()["title"] == "Edited draft title"
    assert edit_response.json()["objective"] == "Edited draft objective"

    run_response = client.post(
        f"/tasks/{task['id']}/steps/{first_step['id']}/runs",
        json={"executor_type": "human", "input": {"note": "too early"}},
    )
    assert run_response.status_code == 400
    assert "Plan must be approved" in run_response.text


def test_steps_run_sequentially(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    first_step, second_step = detail["steps"]

    early_second_run = client.post(
        f"/tasks/{task['id']}/steps/{second_step['id']}/runs",
        json={"executor_type": "human", "input": {"note": "too early"}},
    )
    assert early_second_run.status_code == 400

    detail = client.get(f"/tasks/{task['id']}").json()
    start_actions = [action for action in detail["next_actions"] if action["action_type"] == "start_step_run"]
    assert len(start_actions) == 1
    assert start_actions[0]["target"] == {"task_id": task["id"], "step_id": first_step["id"]}

    run = create_run(client, task["id"], first_step["id"])
    detail = client.get(f"/tasks/{task['id']}").json()
    assert [action for action in detail["next_actions"] if action["action_type"] == "start_step_run"] == []

    submit_run(client, task["id"], first_step["id"], run["id"])
    client.post(
        f"/tasks/{task['id']}/steps/{first_step['id']}/runs/{run['id']}/review",
        json={"decision": "approved"},
    )

    second_run = create_run(client, task["id"], second_step["id"])
    assert second_run["status"] == "running"
    detail = client.get(f"/tasks/{task['id']}").json()
    assert detail["current_pointer"]["step_id"] == second_step["id"]
    assert detail["current_pointer"]["run_id"] == second_run["id"]


def test_request_revision_and_rerun_preserve_history(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]
    run = create_run(client, task["id"], step["id"], "human")
    submit_run(client, task["id"], step["id"], run["id"])

    response = client.post(
        f"/tasks/{task['id']}/steps/{step['id']}/runs/{run['id']}/review",
        json={"decision": "request_revision", "comment": "Needs more detail"},
    )
    assert response.status_code == 200, response.text

    detail = client.get(f"/tasks/{task['id']}").json()
    assert detail["task"]["status"] == "needs_revision"
    revised_step = next(item for item in detail["steps"] if item["id"] == step["id"])
    assert revised_step["status"] == "needs_revision"
    assert detail["next_actions"][0]["action_type"] == "rerun_step"
    assert detail["next_actions"][0]["target"]["task_id"] == task["id"]
    assert detail["next_actions"][0]["target"]["step_id"] == step["id"]

    rerun_response = client.post(
        f"/tasks/{task['id']}/steps/{step['id']}/rerun",
        json={"executor_type": "human", "input": {"note": "revision"}},
    )
    assert rerun_response.status_code == 200, rerun_response.text
    rerun = rerun_response.json()
    assert rerun["comparison_group_id"] is None
    assert rerun["forked_step_id"] != step["id"]

    original_runs = client.get(f"/tasks/{task['id']}/steps/{step['id']}/runs").json()
    assert len(original_runs) == 1
    assert original_runs[0]["attempt_number"] == 1
    assert original_runs[0]["status"] == "rejected"

    detail = client.get(f"/tasks/{task['id']}").json()
    forked_step = next(item for item in detail["steps"] if item["id"] == rerun["forked_step_id"])
    assert forked_step["is_fork"] is True
    assert forked_step["forked_from_step_id"] == step["id"]
    assert forked_step["status"] == "pending"
    assert forked_step["branch_status"] == "active"
    assert client.get(f"/tasks/{task['id']}/steps/{forked_step['id']}/runs").json() == []


def test_approved_historical_step_rerun_creates_branch_without_changing_original_flow(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    first_step, second_step = detail["steps"]
    first_run = create_run(client, task["id"], first_step["id"], "human")
    submit_run(client, task["id"], first_step["id"], first_run["id"])
    client.post(f"/tasks/{task['id']}/steps/{first_step['id']}/runs/{first_run['id']}/review", json={"decision": "approved"})
    second_run = create_run(client, task["id"], second_step["id"], "human")
    submit_run(client, task["id"], second_step["id"], second_run["id"])
    client.post(f"/tasks/{task['id']}/steps/{second_step['id']}/runs/{second_run['id']}/review", json={"decision": "approved"})

    rerun_response = client.post(
        f"/tasks/{task['id']}/steps/{first_step['id']}/rerun",
        json={"executor_type": "human", "input": {"note": "redo first"}, "change_request": "Add a hello button"},
    )
    assert rerun_response.status_code == 200, rerun_response.text
    rerun = rerun_response.json()
    assert rerun["cloned_steps_count"] == 1

    detail = client.get(f"/tasks/{task['id']}").json()
    first_after = next(item for item in detail["steps"] if item["id"] == first_step["id"])
    second_after = next(item for item in detail["steps"] if item["id"] == second_step["id"])
    forked_step = next(item for item in detail["steps"] if item["id"] == rerun["forked_step_id"])
    cloned_step = next(item for item in detail["steps"] if item["cloned_from_step_id"] == second_step["id"])
    assert first_after["status"] == "approved"
    assert first_after["approved_run_id"] == first_run["id"]
    assert second_after["status"] == "approved"
    assert second_after["approved_run_id"] == second_run["id"]
    assert forked_step["status"] == "pending"
    assert forked_step["is_fork"] is True
    assert forked_step["forked_from_step_id"] == first_step["id"]
    assert "Change request: Add a hello button" in forked_step["objective"]
    assert first_after["next_step_ids"] == [second_step["id"]]
    assert forked_step["previous_step_ids"] == []
    assert forked_step["next_step_ids"] == [cloned_step["id"]]
    assert cloned_step["status"] == "pending"
    assert cloned_step["is_fork"] is True
    assert cloned_step["comparison_group_id"] is None
    assert cloned_step["previous_step_ids"] == [forked_step["id"]]
    assert client.get(f"/tasks/{task['id']}/steps/{forked_step['id']}/runs").json() == []

    second_runs = client.get(f"/tasks/{task['id']}/steps/{second_step['id']}/runs").json()
    assert len(second_runs) == 1
    assert second_runs[0]["status"] == "accepted"

    timeline = client.get(f"/tasks/{task['id']}/timeline").json()
    event_types = [event["event_type"] for event in timeline]
    assert "step_downstream_invalidated" not in event_types
    assert "step_rerun_branch_created" in event_types
    branch_clone = next(event for event in timeline if event["event_type"] == "step_branch_cloned")
    assert branch_clone["payload"]["source_step_id"] == first_step["id"]
    assert branch_clone["payload"]["forked_step_id"] == rerun["forked_step_id"]
    assert branch_clone["payload"]["cloned_steps_count"] == 1


def test_rerun_from_branch_clones_only_that_branch_suffix(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    first_step, second_step = detail["steps"]
    first_run = create_run(client, task["id"], first_step["id"], "human")
    submit_run(client, task["id"], first_step["id"], first_run["id"])
    client.post(f"/tasks/{task['id']}/steps/{first_step['id']}/runs/{first_run['id']}/review", json={"decision": "approved"})
    second_run = create_run(client, task["id"], second_step["id"], "human")
    submit_run(client, task["id"], second_step["id"], second_run["id"])
    client.post(f"/tasks/{task['id']}/steps/{second_step['id']}/runs/{second_run['id']}/review", json={"decision": "approved"})

    first_branch_response = client.post(
        f"/tasks/{task['id']}/steps/{first_step['id']}/rerun",
        json={"executor_type": "human", "input": {"note": "first branch"}},
    )
    assert first_branch_response.status_code == 200, first_branch_response.text
    first_branch = first_branch_response.json()
    first_branch_run = create_run(client, task["id"], first_branch["forked_step_id"], "human")
    client.post(
        f"/tasks/{task['id']}/steps/{first_branch['forked_step_id']}/runs/{first_branch_run['id']}/submit",
        json={"output": {"summary": "branch root ready"}},
    )
    client.post(
        f"/tasks/{task['id']}/steps/{first_branch['forked_step_id']}/runs/{first_branch_run['id']}/review",
        json={"decision": "approved"},
    )
    detail = client.get(f"/tasks/{task['id']}").json()
    first_branch_clone = next(item for item in detail["steps"] if item["cloned_from_step_id"] == second_step["id"])

    second_branch_response = client.post(
        f"/tasks/{task['id']}/steps/{first_branch['forked_step_id']}/rerun",
        json={"executor_type": "human", "input": {"note": "nested branch"}},
    )
    assert second_branch_response.status_code == 200, second_branch_response.text
    second_branch = second_branch_response.json()
    assert second_branch["cloned_steps_count"] == 1

    detail = client.get(f"/tasks/{task['id']}").json()
    nested_clones = [item for item in detail["steps"] if item["clone_batch_id"] and item["clone_batch_id"] != first_branch_clone["clone_batch_id"] and item["cloned_from_step_id"]]
    assert len(nested_clones) == 1
    assert nested_clones[0]["cloned_from_step_id"] == first_branch_clone["id"]


def test_branch_path_continues_to_downstream_clone_after_approved_rerun_branch(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    first_step, second_step = detail["steps"]
    first_run = create_run(client, task["id"], first_step["id"], "human")
    submit_run(client, task["id"], first_step["id"], first_run["id"])
    client.post(f"/tasks/{task['id']}/steps/{first_step['id']}/runs/{first_run['id']}/review", json={"decision": "approved"})
    second_run = create_run(client, task["id"], second_step["id"], "human")
    submit_run(client, task["id"], second_step["id"], second_run["id"])
    client.post(f"/tasks/{task['id']}/steps/{second_step['id']}/runs/{second_run['id']}/review", json={"decision": "approved"})

    first_branch = client.post(
        f"/tasks/{task['id']}/steps/{first_step['id']}/rerun",
        json={"executor_type": "human", "input": {"note": "first branch"}},
    ).json()
    first_branch_run = create_run(client, task["id"], first_branch["forked_step_id"], "human")
    client.post(
        f"/tasks/{task['id']}/steps/{first_branch['forked_step_id']}/runs/{first_branch_run['id']}/submit",
        json={"output": {"summary": "branch root ready"}},
    )
    client.post(
        f"/tasks/{task['id']}/steps/{first_branch['forked_step_id']}/runs/{first_branch_run['id']}/review",
        json={"decision": "approved"},
    )
    detail = client.get(f"/tasks/{task['id']}").json()
    first_branch_clone = next(item for item in detail["steps"] if item["cloned_from_step_id"] == second_step["id"])
    first_clone_run = create_run(client, task["id"], first_branch_clone["id"], "human")
    submit_run(client, task["id"], first_branch_clone["id"], first_clone_run["id"])
    client.post(f"/tasks/{task['id']}/steps/{first_branch_clone['id']}/runs/{first_clone_run['id']}/review", json={"decision": "approved"})

    second_branch = client.post(
        f"/tasks/{task['id']}/steps/{first_branch['forked_step_id']}/rerun",
        json={"executor_type": "human", "input": {"note": "nested branch"}},
    ).json()
    second_branch_run = create_run(client, task["id"], second_branch["forked_step_id"], "human")
    client.post(
        f"/tasks/{task['id']}/steps/{second_branch['forked_step_id']}/runs/{second_branch_run['id']}/submit",
        json={"output": {"summary": "nested branch root ready"}},
    )
    client.post(
        f"/tasks/{task['id']}/steps/{second_branch['forked_step_id']}/runs/{second_branch_run['id']}/review",
        json={"decision": "approved"},
    )

    detail = client.get(f"/tasks/{task['id']}").json()
    steps = detail["steps"]
    second_branch_root = next(item for item in steps if item["id"] == second_branch["forked_step_id"])
    next_clone = next(
        item
        for item in steps
        if item["clone_batch_id"] == second_branch_root["clone_batch_id"]
        and item["cloned_from_step_id"] == first_branch_clone["id"]
    )
    start_actions = [action for action in detail["next_actions"] if action["action_type"] == "start_step_run"]
    assert detail["current_pointer"]["step_id"] == next_clone["id"]
    assert [action["target"]["step_id"] for action in start_actions] == [next_clone["id"]]



def test_historical_step_cannot_create_rerun_branch_while_another_step_is_running(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    first_step, second_step = detail["steps"]
    first_run = create_run(client, task["id"], first_step["id"], "human")
    submit_run(client, task["id"], first_step["id"], first_run["id"])
    client.post(f"/tasks/{task['id']}/steps/{first_step['id']}/runs/{first_run['id']}/review", json={"decision": "approved"})
    create_run(client, task["id"], second_step["id"], "human")

    response = client.post(
        f"/tasks/{task['id']}/steps/{first_step['id']}/rerun",
        json={"executor_type": "human", "input": {"note": "blocked redo"}},
    )

    assert response.status_code == 400
    assert "Cannot create a rerun branch" in response.text


def test_timeline_and_empty_artifacts(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]
    run = create_run(client, task["id"], step["id"], "human")
    submit_run(client, task["id"], step["id"], run["id"])
    client.post(f"/tasks/{task['id']}/steps/{step['id']}/runs/{run['id']}/review", json={"decision": "approved"})

    timeline = client.get(f"/tasks/{task['id']}/timeline").json()
    event_types = [event["event_type"] for event in timeline]
    for event_type in [
        "task_created",
        "task_message_added",
        "task_revision_created",
        "task_plan_generated",
        "task_plan_approved",
        "step_added",
        "step_run_started",
        "step_run_submitted",
        "step_run_reviewed",
        "step_approved",
        "progress_recalculated",
    ]:
        assert event_type in event_types

    artifacts = client.get(f"/tasks/{task['id']}/artifacts").json()
    assert artifacts == []


def test_executor_type_rejects_forbidden_values(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    step = detail["steps"][0]
    for value in ["skill", "cli"]:
        response = client.post(
            f"/tasks/{task['id']}/steps/{step['id']}/runs",
            json={"executor_type": value, "input": {}},
        )
        assert response.status_code == 422


def test_project_terms_do_not_include_forbidden_strings():
    root = Path(__file__).resolve().parents[3]
    scanned = []
    excluded_dirs = {".venv", ".venv311", "__pycache__", ".pytest_cache"}
    for path in [root / "README.md", root / "docs", root / "backend"]:
        if path.is_file():
            scanned.append(path)
        elif path.exists():
            scanned.extend(
                item
                for item in path.rglob("*")
                if item.is_file()
                and item.suffix in {".md", ".py"}
                and not excluded_dirs.intersection(item.parts)
                and item.name != "test_phase1_flow.py"
            )
    content = "\n".join(item.read_text() for item in scanned)
    forbidden_terms = ["Task" + "Draft", "task" + "_drafts", "tool" + "_type="]
    for term in forbidden_terms:
        assert term not in content
