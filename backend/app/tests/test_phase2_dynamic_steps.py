from test_phase1_flow import approve_plan, create_task, generate_plan


def test_append_insert_skip_supersede_and_next_actions(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    first, second = detail["steps"]

    appended = client.post(
        f"/tasks/{task['id']}/steps",
        json={"title": "Append", "description": "Append objective", "insert_mode": "append_to_end", "created_reason": "test"},
    )
    assert appended.status_code == 200, appended.text
    assert appended.json()["is_dynamic"] is True

    inserted_after = client.post(
        f"/tasks/{task['id']}/steps",
        json={"title": "After first", "description": "Inserted after first", "insert_mode": "insert_after_step", "target_step_id": first["id"]},
    )
    assert inserted_after.status_code == 200, inserted_after.text

    inserted_before = client.post(
        f"/tasks/{task['id']}/steps",
        json={"title": "Before second", "description": "Inserted before second", "insert_mode": "insert_before_step", "target_step_id": second["id"]},
    )
    assert inserted_before.status_code == 200, inserted_before.text

    steps = client.get(f"/tasks/{task['id']}/steps").json()
    ordered_titles = [step["title"] for step in steps]
    assert ordered_titles.index("After first") == ordered_titles.index("Step one") + 1
    assert ordered_titles.index("Before second") < ordered_titles.index("Step two")

    skip = client.post(f"/tasks/{task['id']}/steps/{inserted_after.json()['id']}/skip", json={"reason": "not needed", "actor_id": "local-user"})
    assert skip.status_code == 200, skip.text
    assert skip.json()["status"] == "skipped"

    supersede = client.post(
        f"/tasks/{task['id']}/steps/{inserted_before.json()['id']}/supersede",
        json={"new_step": {"title": "Replacement", "description": "Replacement objective"}, "reason": "better path", "actor_id": "local-user"},
    )
    assert supersede.status_code == 200, supersede.text
    replacement = supersede.json()
    assert replacement["supersedes_step_id"] == inserted_before.json()["id"]

    detail = client.get(f"/tasks/{task['id']}").json()
    action_types = {action["action_type"] for action in detail["next_actions"]}
    assert {"add_step", "skip_step", "supersede_step", "reorder_step"}.issubset(action_types)
    for action in detail["next_actions"]:
        assert action["target"]["task_id"] == task["id"]
        if action["target_type"] == "step":
            assert action["target"].get("step_id") is not None

    events = [event["event_type"] for event in client.get(f"/tasks/{task['id']}/timeline").json()]
    for event_type in ["step_added", "step_inserted", "step_skipped", "step_superseded", "progress_recalculated"]:
        assert event_type in events


def test_archived_and_completed_task_reject_dynamic_step(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    first, second = detail["steps"]
    for step in [first, second]:
        skip = client.post(f"/tasks/{task['id']}/steps/{step['id']}/skip", json={})
        assert skip.status_code == 200, skip.text

    completed_add = client.post(f"/tasks/{task['id']}/steps", json={"title": "Late", "description": "Too late"})
    assert completed_add.status_code == 400


def test_approved_step_cannot_skip_or_core_edit(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]
    run = client.post(f"/tasks/{task['id']}/steps/{step['id']}/runs", json={"executor_type": "human", "input": {}}).json()
    client.post(f"/tasks/{task['id']}/steps/{step['id']}/runs/{run['id']}/submit", json={"output": {}})
    client.post(f"/tasks/{task['id']}/steps/{step['id']}/runs/{run['id']}/review", json={"decision": "approved"})

    skip = client.post(f"/tasks/{task['id']}/steps/{step['id']}/skip", json={})
    assert skip.status_code == 400
    edit = client.patch(f"/tasks/{task['id']}/steps/{step['id']}", json={"title": "Changed"})
    assert edit.status_code == 400
