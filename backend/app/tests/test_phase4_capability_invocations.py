from test_phase1_flow import approve_plan, create_run, create_task, generate_plan


def setup_running_run(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]
    run = create_run(client, task["id"], step["id"])
    return task, step, run


def test_capability_registry_returns_list_and_detail(client):
    response = client.get("/capabilities")
    assert response.status_code == 200, response.text
    capabilities = response.json()
    assert any(item["capability_id"] == "generate_report" for item in capabilities)

    detail = client.get("/capabilities/generate_report")
    assert detail.status_code == 200, detail.text
    assert detail.json()["adapter_id"] == "record_only"

    missing = client.get("/capabilities/missing")
    assert missing.status_code == 404


def test_create_update_and_list_capability_invocation(client):
    task, step, run = setup_running_run(client)
    response = client.post(
        f"/tasks/{task['id']}/steps/{step['id']}/runs/{run['id']}/capability-invocations",
        json={"capability_id": "generate_report", "input": {"topic": "task summary"}, "invoked_by_type": "agent", "invoked_by_id": "agent-1"},
    )
    assert response.status_code == 200, response.text
    invocation = response.json()
    assert invocation["status"] == "pending"
    assert invocation["capability_name"] == "Generate report"
    assert invocation["adapter_id"] == "record_only"
    assert invocation["input"] == {"topic": "task summary"}
    assert invocation["artifacts"] == []

    update = client.patch(
        f"/tasks/{task['id']}/capability-invocations/{invocation['id']}",
        json={
            "status": "succeeded",
            "output": {"summary": "Capability result recorded"},
            "duration_ms": 1200,
            "artifacts": [{"type": "report", "name": "summary", "metadata": {"kind": "demo"}}],
        },
    )
    updated_invocation = update.json()
    assert updated_invocation["output"] == {"summary": "Capability result recorded"}
    assert updated_invocation["completed_at"] is not None
    assert updated_invocation["artifacts"] == [{"type": "report", "name": "summary", "uri": None, "metadata": {"kind": "demo"}}]

    all_invocations = client.get(f"/tasks/{task['id']}/capability-invocations").json()
    run_invocations = client.get(f"/tasks/{task['id']}/steps/{step['id']}/runs/{run['id']}/capability-invocations").json()
    assert len(all_invocations) == 1
    assert len(run_invocations) == 1
    assert all_invocations[0]["capability_name"] == "Generate report"
    assert all_invocations[0]["completed_at"] is not None

    detail = client.get(f"/tasks/{task['id']}").json()
    assert detail["capability_invocations_count"] == 1
    assert detail["latest_capability_invocations"][0]["capability_id"] == "generate_report"
    assert detail["latest_capability_invocations"][0]["completed_at"] is not None

    artifacts = client.get(f"/tasks/{task['id']}/artifacts").json()
    assert artifacts[0]["capability_invocation_id"] == invocation["id"]
    assert artifacts[0]["metadata"] == {"kind": "demo"}

    events = [event["event_type"] for event in client.get(f"/tasks/{task['id']}/timeline").json()]
    assert "capability_invocation_recorded" in events
    assert "capability_invocation_updated" in events
    assert "artifact_created" in events


def test_capability_invocation_rejects_forbidden_executor_and_unknown_capability(client):
    task, step, run = setup_running_run(client)
    for value in ["codex", "skill", "cli"]:
        response = client.post(
            f"/tasks/{task['id']}/steps/{step['id']}/runs/{run['id']}/capability-invocations",
            json={"capability_id": "generate_report", "input": {}, "invoked_by_type": value},
        )
        assert response.status_code == 422

    missing = client.post(
        f"/tasks/{task['id']}/steps/{step['id']}/runs/{run['id']}/capability-invocations",
        json={"capability_id": "missing", "input": {}, "invoked_by_type": "agent"},
    )
    assert missing.status_code == 404


def test_capability_update_failed_saves_error_and_next_action_exists(client):
    task, step, run = setup_running_run(client)
    detail = client.get(f"/tasks/{task['id']}").json()
    actions = {action["action_type"]: action for action in detail["next_actions"]}
    assert "record_capability_invocation" in actions
    assert actions["record_capability_invocation"]["target"] == {"task_id": task["id"], "step_id": step["id"], "run_id": run["id"]}

    invocation = client.post(
        f"/tasks/{task['id']}/steps/{step['id']}/runs/{run['id']}/capability-invocations",
        json={"capability_id": "run_tests", "input": {}, "invoked_by_type": "worker"},
    ).json()
    failed = client.patch(
        f"/tasks/{task['id']}/capability-invocations/{invocation['id']}",
        json={"status": "failed", "error": "Recorded failure"},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["error"] == "Recorded failure"
