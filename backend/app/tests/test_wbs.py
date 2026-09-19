def create_task(client, title: str) -> int:
    response = client.post(
        "/tasks",
        json={"title": title, "goal": f"Complete {title}", "executor_mode": "agent"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def complete_task(client, task_id: int) -> None:
    generated = client.post(
        f"/tasks/{task_id}/generate-plan",
        json={"reason": "WBS progress test", "steps": [{"title": "Execute", "objective": "Complete the work"}]},
    )
    assert generated.status_code == 200, generated.text
    approved = client.post(f"/tasks/{task_id}/approve-plan", json={"decision": "approved"})
    assert approved.status_code == 200, approved.text
    step_id = approved.json()["steps"][0]["id"]
    run = client.post(
        f"/tasks/{task_id}/steps/{step_id}/runs",
        json={"executor_type": "human", "input": {}},
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["id"]
    submitted = client.post(
        f"/tasks/{task_id}/steps/{step_id}/runs/{run_id}/submit",
        json={"output": {"summary": "done"}},
    )
    assert submitted.status_code == 200, submitted.text
    reviewed = client.post(
        f"/tasks/{task_id}/steps/{step_id}/runs/{run_id}/review",
        json={"decision": "approved"},
    )
    assert reviewed.status_code == 200, reviewed.text


def create_root(client, task_id: int, title: str = "Program") -> dict:
    response = client.post(
        f"/tasks/{task_id}/wbs-nodes",
        json={"title": title, "node_type": "work", "position": 1},
    )
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, proposal_id: int) -> dict:
    response = client.post(
        f"/wbs/change-proposals/{proposal_id}/decision",
        json={"decision": "approved", "note": "Approved in test", "decided_by_id": "tester"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def propose_and_approve_child(client, parent_id: int, title: str, position: int, task_id: int | None = None) -> dict:
    payload = {"title": title, "node_type": "work", "position": position}
    if task_id is not None:
        payload["execution_task_id"] = task_id
    proposed = client.post(f"/wbs/{parent_id}/children", json=payload)
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()["status"] == "draft"
    approve(client, proposed.json()["id"])
    return proposed.json()


def test_wbs_root_is_bound_to_url_task_and_unique(client):
    task_id = create_task(client, "Root task")
    other_task_id = create_task(client, "Other task")

    mismatch = client.post(
        f"/tasks/{task_id}/wbs-nodes",
        json={"title": "Wrong root", "execution_task_id": other_task_id},
    )
    assert mismatch.status_code == 400

    tree = create_root(client, task_id)
    assert tree["root_id"] == tree["nodes"][0]["id"]
    assert tree["nodes"][0]["execution_task_id"] == task_id
    assert tree["nodes"][0]["depth"] == 0
    assert tree["rollup"]["progress_percent"] == 0

    duplicate = client.post(f"/tasks/{task_id}/wbs-nodes", json={"title": "Duplicate"})
    assert duplicate.status_code == 409


def test_child_creation_is_reviewed_and_depth_first(client):
    root_task_id = create_task(client, "Root")
    child_task_id = create_task(client, "Child")
    tree = create_root(client, root_task_id)
    root_id = tree["root_id"]

    proposal = client.post(
        f"/wbs/{root_id}/children",
        json={"title": "Child work", "position": 1, "execution_task_id": child_task_id},
    )
    assert proposal.status_code == 200, proposal.text
    body = proposal.json()
    assert body["status"] == "draft"
    assert body["base_version"] == 1
    assert len(body["before"]["nodes"]) == 1
    assert len(body["after"]["nodes"]) == 2
    assert client.get(f"/tasks/{root_task_id}/wbs").json()["nodes"] == tree["nodes"]

    approve(client, body["id"])
    updated = client.get(f"/tasks/{root_task_id}/wbs")
    assert updated.status_code == 200, updated.text
    updated_tree = updated.json()
    assert updated_tree["version"] == 2
    assert [node["title"] for node in updated_tree["nodes"]] == ["Program", "Child work"]
    assert [node["depth"] for node in updated_tree["nodes"]] == [0, 1]
    assert updated_tree["rollup"]["reportable_node_count"] == 1

    child_node = updated_tree["nodes"][1]
    by_child_task = client.get(f"/tasks/{child_task_id}/wbs")
    assert by_child_task.status_code == 200
    assert by_child_task.json()["root_id"] == root_id
    assert child_node["execution_task_id"] == child_task_id


def test_rollup_uses_direct_children_without_double_counting_descendants(client):
    root_task_id = create_task(client, "Root")
    completed_task_id = create_task(client, "Completed child")
    pending_task_id = create_task(client, "Pending grandchild")
    complete_task(client, completed_task_id)
    root_id = create_root(client, root_task_id)["root_id"]

    propose_and_approve_child(client, root_id, "Completed child", 1, completed_task_id)
    tree = client.get(f"/tasks/{root_task_id}/wbs").json()
    completed_node_id = next(node["id"] for node in tree["nodes"] if node["execution_task_id"] == completed_task_id)
    propose_and_approve_child(client, completed_node_id, "Pending grandchild", 1, pending_task_id)

    updated = client.get(f"/tasks/{root_task_id}/wbs").json()
    completed_parent = next(node for node in updated["nodes"] if node["id"] == completed_node_id)
    assert completed_parent["progress_percent"] == 0
    assert updated["rollup"]["progress_percent"] == 0
    assert updated["rollup"]["reportable_node_count"] == 1


def test_critical_path_uses_topological_order_not_node_ids(client):
    root_task_id = create_task(client, "Root")
    first_task_id = create_task(client, "First")
    second_task_id = create_task(client, "Second")
    root_id = create_root(client, root_task_id)["root_id"]

    propose_and_approve_child(client, root_id, "Created first but downstream", 2, second_task_id)
    propose_and_approve_child(client, root_id, "Created second but upstream", 1, first_task_id)
    tree = client.get(f"/tasks/{root_task_id}/wbs").json()
    downstream_id = next(node["id"] for node in tree["nodes"] if node["execution_task_id"] == second_task_id)
    upstream_id = next(node["id"] for node in tree["nodes"] if node["execution_task_id"] == first_task_id)
    assert upstream_id > downstream_id

    proposal = client.post(
        f"/wbs/{root_id}/dependencies",
        json={"predecessor_id": upstream_id, "successor_id": downstream_id},
    )
    assert proposal.status_code == 200, proposal.text
    approve(client, proposal.json()["id"])

    updated = client.get(f"/tasks/{root_task_id}/wbs").json()
    assert updated["critical_path"]["node_ids"] == [upstream_id, downstream_id]


def test_dependency_requires_same_tree_and_approval(client):
    root_task_id = create_task(client, "Root")
    first_task_id = create_task(client, "First")
    second_task_id = create_task(client, "Second")
    other_root_task_id = create_task(client, "Other root")
    root_id = create_root(client, root_task_id)["root_id"]
    other_root_id = create_root(client, other_root_task_id, "Other program")["root_id"]

    propose_and_approve_child(client, root_id, "First", 1, first_task_id)
    propose_and_approve_child(client, root_id, "Second", 2, second_task_id)
    tree = client.get(f"/tasks/{root_task_id}/wbs").json()
    first_id, second_id = [node["id"] for node in tree["nodes"] if node["parent_id"] == root_id]

    cross_tree = client.post(
        f"/wbs/{root_id}/dependencies",
        json={"predecessor_id": first_id, "successor_id": other_root_id},
    )
    assert cross_tree.status_code == 400

    dependency = client.post(
        f"/wbs/{root_id}/dependencies",
        json={"predecessor_id": first_id, "successor_id": second_id, "reason": "First before second"},
    )
    assert dependency.status_code == 200, dependency.text
    assert client.get(f"/tasks/{root_task_id}/wbs").json()["dependencies"] == []
    approve(client, dependency.json()["id"])

    updated = client.get(f"/tasks/{root_task_id}/wbs").json()
    assert updated["dependencies"][0]["predecessor_id"] == first_id
    second = next(node for node in updated["nodes"] if node["id"] == second_id)
    assert second["status"] == "blocked"
    assert second["blocked_by_node_ids"] == [first_id]
    assert updated["critical_path"]["node_ids"] == [first_id, second_id]

    cycle = client.post(
        f"/wbs/{root_id}/dependencies",
        json={"predecessor_id": second_id, "successor_id": first_id},
    )
    assert cycle.status_code == 400


def test_proposal_reject_and_stale_version_are_audited(client):
    task_id = create_task(client, "Root")
    root_id = create_root(client, task_id)["root_id"]

    first = client.post(f"/wbs/{root_id}/children", json={"title": "First", "position": 1}).json()
    second = client.post(f"/wbs/{root_id}/children", json={"title": "Second", "position": 1}).json()

    rejected = client.post(
        f"/wbs/change-proposals/{first['id']}/decision",
        json={"decision": "rejected", "note": "Not now"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    repeated = client.post(
        f"/wbs/change-proposals/{first['id']}/decision",
        json={"decision": "approved"},
    )
    assert repeated.status_code == 409

    approve(client, second["id"])
    stale = client.post(
        f"/wbs/change-proposals/{first['id']}/decision",
        json={"decision": "approved"},
    )
    assert stale.status_code == 409

    timeline = client.get(f"/tasks/{task_id}/timeline")
    assert timeline.status_code == 200
    event_types = [event["event_type"] for event in timeline.json()]
    assert "wbs_change_proposed" in event_types
    assert "wbs_change_rejected" in event_types
    assert "wbs_change_approved" in event_types


def test_stale_draft_is_rejected_after_another_proposal_is_approved(client):
    task_id = create_task(client, "Root")
    root_id = create_root(client, task_id)["root_id"]
    first = client.post(f"/wbs/{root_id}/children", json={"title": "First", "position": 1}).json()
    second = client.post(f"/wbs/{root_id}/children", json={"title": "Second", "position": 1}).json()

    approve(client, first["id"])
    stale = client.post(
        f"/wbs/change-proposals/{second['id']}/decision",
        json={"decision": "approved"},
    )
    assert stale.status_code == 409
    assert "version" in stale.json()["detail"].lower()


def test_proposal_rejects_derived_fields_and_tree_cycles(client):
    task_id = create_task(client, "Root")
    tree = create_root(client, task_id)
    root_id = tree["root_id"]
    root = tree["nodes"][0]
    valid_root = {
        "id": root_id,
        "parent_id": None,
        "execution_task_id": task_id,
        "node_type": "work",
        "title": "Program",
        "position": 1,
        "is_active": True,
    }

    forged = client.post(
        f"/wbs/{root_id}/change-proposals",
        json={"after": {"nodes": [{**valid_root, "progress_percent": 100}], "dependencies": []}},
    )
    assert forged.status_code == 422

    cyclic = client.post(
        f"/wbs/{root_id}/change-proposals",
        json={
            "after": {
                "nodes": [
                    {**valid_root, "parent_id": -1},
                    {"id": -1, "parent_id": root_id, "node_type": "work", "title": "Cycle", "position": 1},
                ],
                "dependencies": [],
            }
        },
    )
    assert cyclic.status_code == 400


def test_sqlite_wbs_schema_upgrade_is_idempotent(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, inspect, text

    from app import db as db_module
    from app.db import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title VARCHAR(255) NOT NULL, goal TEXT NOT NULL, status VARCHAR(50) NOT NULL)"))
        connection.execute(text("CREATE TABLE task_steps (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, title VARCHAR(255) NOT NULL, objective TEXT NOT NULL, status VARCHAR(50) NOT NULL, position INTEGER NOT NULL)"))
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "DATABASE_URL", f"sqlite:///{tmp_path / 'legacy.db'}")

    db_module.ensure_sqlite_schema()
    db_module.ensure_sqlite_schema()

    inspector = inspect(engine)
    assert {"wbs_nodes", "wbs_milestones", "wbs_dependencies", "wbs_change_proposals"}.issubset(inspector.get_table_names())
    index_names = {index["name"] for index in inspector.get_indexes("wbs_nodes")}
    assert "ix_wbs_nodes_root_parent" in index_names


def test_milestone_status_is_derived(client):
    task_id = create_task(client, "Root")
    root_id = create_root(client, task_id)["root_id"]

    missing = client.post(f"/wbs/{root_id}/milestones", json={"title": "Done", "criteria": ""})
    assert missing.status_code == 422

    created = client.post(
        f"/wbs/{root_id}/milestones",
        json={"title": "Acceptance", "criteria": "All approved steps are complete"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "open"

    forged = client.patch(
        f"/wbs/milestones/{created.json()['id']}",
        json={"status": "completed"},
    )
    assert forged.status_code == 422

    updated = client.patch(
        f"/wbs/milestones/{created.json()['id']}",
        json={"criteria": "Task must reach completed status"},
    )
    assert updated.status_code == 200
    assert updated.json()["criteria"] == "Task must reach completed status"
