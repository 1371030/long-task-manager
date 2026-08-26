from pathlib import Path

from app.services import task_service
from app.tests.test_phase1_flow import approve_plan, create_run, create_task, generate_plan, submit_run


def prepared_task(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    return task, detail["steps"]


def create_review(client, task_id, expected):
    response = client.post(
        f"/tasks/{task_id}/progress-reviews",
        json={"expected_progress_percent": expected, "created_by_id": "reviewer"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def decide_review(client, task_id, review_id, decision="keep_plan", note="Reviewed"):
    response = client.post(
        f"/tasks/{task_id}/progress-reviews/{review_id}/decision",
        json={"decision": decision, "note": note, "decided_by_id": "reviewer"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_progress_review_classification_boundaries_and_history(client):
    task, _ = prepared_task(client)

    on_track = create_review(client, task["id"], 5)
    assert on_track["actual_progress_percent"] == 0
    assert on_track["variance_percentage_points"] == -5
    assert on_track["classification"] == "on_track"
    assert on_track["previous_review_id"] is None
    decide_review(client, task["id"], on_track["id"])

    behind = create_review(client, task["id"], 5.01)
    assert behind["classification"] == "behind"
    assert behind["previous_review_id"] == on_track["id"]
    decide_review(client, task["id"], behind["id"], "adjust_plan", "Review remaining scope")

    ahead = create_review(client, task["id"], 0)
    assert ahead["classification"] == "on_track"
    decide_review(client, task["id"], ahead["id"])

    run = create_run(client, task["id"], client.get(f"/tasks/{task['id']}/steps").json()[0]["id"])
    submit_run(client, task["id"], run["step_id"], run["id"])
    client.post(f"/tasks/{task['id']}/steps/{run['step_id']}/runs/{run['id']}/review", json={"decision": "approved"})
    ahead = create_review(client, task["id"], 44.99)
    assert ahead["actual_progress_percent"] == 50
    assert ahead["variance_percentage_points"] == 5.01
    assert ahead["classification"] == "ahead"

    history = client.get(f"/tasks/{task['id']}/progress-reviews")
    assert history.status_code == 200, history.text
    assert [item["id"] for item in history.json()] == [ahead["id"], on_track["id"] + 2, behind["id"], on_track["id"]]


def test_review_requires_decision_and_preserves_workflow_state(client):
    task, steps = prepared_task(client)
    review = create_review(client, task["id"], 60)

    blocked = client.post(f"/tasks/{task['id']}/progress-reviews", json={"expected_progress_percent": 70})
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "Decide the latest progress review before creating another"

    status_before = client.get(f"/tasks/{task['id']}").json()["task"]["status"]
    decided = decide_review(client, task["id"], review["id"], "adjust_plan", "Add a clarification step")
    assert decided["decision"] == "adjust_plan"
    assert decided["decision_note"] == "Add a clarification step"
    assert client.get(f"/tasks/{task['id']}").json()["task"]["status"] == status_before

    duplicate = client.post(
        f"/tasks/{task['id']}/progress-reviews/{review['id']}/decision",
        json={"decision": "keep_plan"},
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "Progress review has already been decided"

    add_step = client.post(
        f"/tasks/{task['id']}/steps",
        json={"title": "Clarify scope", "objective": "Clarify the remaining work", "insert_mode": "insert_after_step", "target_step_id": steps[0]["id"]},
    )
    assert add_step.status_code == 200, add_step.text
    assert review["snapshot"]["active_steps_total"] == 2
    assert create_review(client, task["id"], 60)["snapshot"]["active_steps_total"] == 3


def test_review_records_failures_retries_events_and_task_log(client, tmp_path, monkeypatch):
    monkeypatch.setattr(task_service, "TASK_LOG_DIR", tmp_path / "task_logs")
    task, steps = prepared_task(client)
    run = create_run(client, task["id"], steps[0]["id"])
    submit_run(client, task["id"], steps[0]["id"], run["id"])
    rejected = client.post(
        f"/tasks/{task['id']}/steps/{steps[0]['id']}/runs/{run['id']}/review",
        json={"decision": "request_revision", "note": "Needs another attempt"},
    )
    assert rejected.status_code == 200, rejected.text
    retry = client.post(
        f"/tasks/{task['id']}/steps/{steps[0]['id']}/retry",
        json={"executor_type": "human", "input": {"note": "retry"}},
    )
    assert retry.status_code == 200, retry.text

    review = create_review(client, task["id"], 75)
    codes = {observation["code"] for observation in review["observations"]}
    assert {"progress_behind", "rejected_runs", "retries_recorded"} <= codes
    assert "step_needs_revision" not in codes
    assert review["snapshot"]["retry_count"] == 1
    assert any(suggestion["action_type"] == "review_remaining_steps" for suggestion in review["suggestions"])
    decide_review(client, task["id"], review["id"])

    timeline = client.get(f"/tasks/{task['id']}/timeline").json()
    assert {"progress_review_created", "progress_review_decided"} <= {event["event_type"] for event in timeline}
    log_text = Path(task_service.task_log_path(task["id"])).read_text(encoding="utf-8")
    assert "progress_review_created" in log_text
    assert "progress_review_decided" in log_text


def test_review_state_validation_and_not_found(client):
    task = create_task(client)
    response = client.post(f"/tasks/{task['id']}/progress-reviews", json={"expected_progress_percent": 50})
    assert response.status_code == 400
    assert response.json()["detail"] == "Task status intake does not allow progress reviews"

    for invalid in (-0.01, 100.01):
        response = client.post(f"/tasks/{task['id']}/progress-reviews", json={"expected_progress_percent": invalid})
        assert response.status_code == 422

    missing_task = client.get("/tasks/99999/progress-reviews")
    assert missing_task.status_code == 404

    task, _ = prepared_task(client)
    missing_review = client.post(f"/tasks/{task['id']}/progress-reviews/99999/decision", json={"decision": "keep_plan"})
    assert missing_review.status_code == 404
