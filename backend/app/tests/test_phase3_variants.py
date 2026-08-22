from test_phase1_flow import approve_plan, create_task, generate_plan


def test_fork_step_creates_comparison_group_and_next_actions(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]

    response = client.post(
        f"/tasks/{task['id']}/steps/{step['id']}/fork",
        json={
            "variant_label": "alternative",
            "title": "Alternative step",
            "description": "Try another path",
            "fork_reason": "compare options",
            "created_by_type": "human",
            "created_by_id": "local-user",
        },
    )
    assert response.status_code == 200, response.text
    fork = response.json()
    assert fork["comparison_group_id"] is not None
    assert fork["forked_step_id"] is not None

    steps = client.get(f"/tasks/{task['id']}/steps").json()
    original = next(item for item in steps if item["id"] == step["id"])
    forked = next(item for item in steps if item["id"] == fork["forked_step_id"])
    assert original["comparison_group_id"] == fork["comparison_group_id"]
    assert forked["comparison_group_id"] == fork["comparison_group_id"]
    assert forked["forked_from_step_id"] == step["id"]
    assert forked["variant_label"] == "alternative"
    assert forked["branch_status"] == "active"
    assert forked["previous_step_ids"] == []
    assert forked["id"] not in original["next_step_ids"]

    detail = client.get(f"/tasks/{task['id']}").json()
    action_types = {action["action_type"] for action in detail["next_actions"]}
    assert {"fork_step", "compare_step_variants", "select_step_variant"}.issubset(action_types)
    for action in detail["next_actions"]:
        assert action["target"]["task_id"] == task["id"]
        if action["action_type"] == "fork_step":
            assert action["target"].get("step_id") is not None
        if action["action_type"] in {"compare_step_variants", "select_step_variant"}:
            assert action["target"].get("comparison_group_id") == fork["comparison_group_id"]


def test_clone_subtree_and_comparison_summary(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    root = detail["steps"][0]
    child = client.post(
        f"/tasks/{task['id']}/steps",
        json={"title": "Child", "description": "Child objective", "parent_step_id": root["id"]},
    ).json()

    fork = client.post(
        f"/tasks/{task['id']}/steps/{root['id']}/fork",
        json={"variant_label": "clone", "title": "Clone root", "description": "Clone subtree", "clone_subtree": True},
    ).json()
    assert fork["cloned_steps_count"] == 1

    steps = client.get(f"/tasks/{task['id']}/steps").json()
    cloned_child = next(item for item in steps if item.get("cloned_from_step_id") == child["id"])
    assert cloned_child["clone_batch_id"] is not None
    assert cloned_child["comparison_group_id"] == fork["comparison_group_id"]

    comparison = client.get(f"/tasks/{task['id']}/step-comparisons/{fork['comparison_group_id']}")
    assert comparison.status_code == 200, comparison.text
    body = comparison.json()
    assert len(body["variants"]) >= 2
    for variant in body["variants"]:
        assert {"step_id", "variant_label", "status", "branch_status", "runs_count", "approved_run_id", "artifacts_count", "metrics"}.issubset(variant)
        assert {"failed_runs", "accepted_runs"}.issubset(variant["metrics"])
    assert body["next_actions"][0]["action_type"] == "select_step_variant"

    events = [event["event_type"] for event in client.get(f"/tasks/{task['id']}/timeline").json()]
    assert "step_forked" in events
    assert "step_subtree_cloned" in events
    assert "progress_recalculated" in events


def test_variants_run_select_and_progress_rules(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]
    fork = client.post(
        f"/tasks/{task['id']}/steps/{step['id']}/fork",
        json={"variant_label": "variant", "title": "Variant", "description": "Variant objective"},
    ).json()

    steps = client.get(f"/tasks/{task['id']}/steps").json()
    forked = next(item for item in steps if item["id"] == fork["forked_step_id"])
    for variant in [step, forked]:
        run = client.post(f"/tasks/{task['id']}/steps/{variant['id']}/runs", json={"executor_type": "human", "input": {}}).json()
        client.post(f"/tasks/{task['id']}/steps/{variant['id']}/runs/{run['id']}/submit", json={"output": {}})
        client.post(f"/tasks/{task['id']}/steps/{variant['id']}/runs/{run['id']}/review", json={"decision": "approved"})

    unresolved = client.get(f"/tasks/{task['id']}").json()
    assert unresolved["progress"]["active_steps_total"] == 3
    assert unresolved["progress"]["approved_or_skipped_active_steps"] == 2

    selected = client.post(
        f"/tasks/{task['id']}/step-comparisons/{fork['comparison_group_id']}/select",
        json={"selected_step_id": forked["id"], "note": "better", "actor_id": "local-user"},
    )
    assert selected.status_code == 200, selected.text
    group = selected.json()
    assert group["status"] == "resolved"
    assert group["selected_step_id"] == forked["id"]
    assert group["resolved_at"] is not None

    steps = client.get(f"/tasks/{task['id']}/steps").json()
    selected_step = next(item for item in steps if item["id"] == forked["id"])
    not_selected = next(item for item in steps if item["id"] == step["id"])
    assert selected_step["branch_status"] == "selected"
    assert selected_step["is_selected_variant"] is True
    assert not_selected["branch_status"] == "not_selected"
    assert not_selected["is_active"] is False

    rejected_run = client.post(f"/tasks/{task['id']}/steps/{not_selected['id']}/runs", json={"executor_type": "agent", "input": {}})
    assert rejected_run.status_code == 400

    resolved = client.get(f"/tasks/{task['id']}").json()
    assert resolved["progress"]["approved_or_skipped_active_steps"] == 1

    events = [event["event_type"] for event in client.get(f"/tasks/{task['id']}/timeline").json()]
    for event_type in ["step_forked", "step_variant_selected", "comparison_group_resolved", "progress_recalculated"]:
        assert event_type in events


def test_abandon_variant_excludes_it_from_progress(client):
    task = create_task(client)
    detail = generate_plan(client, task["id"])
    approve_plan(client, task["id"])
    step = detail["steps"][0]
    fork = client.post(
        f"/tasks/{task['id']}/steps/{step['id']}/fork",
        json={"variant_label": "abandon", "title": "Abandon", "description": "Abandon objective"},
    ).json()

    run = client.post(f"/tasks/{task['id']}/steps/{fork['forked_step_id']}/runs", json={"executor_type": "agent", "input": {}}).json()
    client.post(f"/tasks/{task['id']}/steps/{fork['forked_step_id']}/runs/{run['id']}/submit", json={"output": {}})
    client.post(f"/tasks/{task['id']}/steps/{fork['forked_step_id']}/runs/{run['id']}/review", json={"decision": "approved"})

    abandon = client.post(f"/tasks/{task['id']}/steps/{fork['forked_step_id']}/abandon-variant", json={"reason": "not needed", "actor_id": "local-user"})
    assert abandon.status_code == 200, abandon.text
    assert abandon.json()["branch_status"] == "abandoned"

    detail = client.get(f"/tasks/{task['id']}").json()
    abandoned = next(item for item in detail["steps"] if item["id"] == fork["forked_step_id"])
    assert abandoned["is_active"] is False
    assert detail["progress"]["approved_or_skipped_active_steps"] == 0
    events = [event["event_type"] for event in client.get(f"/tasks/{task['id']}/timeline").json()]
    assert "step_variant_abandoned" in events
