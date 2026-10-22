def test_capacity_report_aggregates_load_and_distinguishes_unknown(client):
    task = client.post("/tasks", json={"title": "Capacity", "goal": "Review capacity"}).json()
    root = client.post(f"/tasks/{task['id']}/wbs-nodes", json={"title": "Root"}).json()
    child = client.post(f"/wbs/{root['root_id']}/children", json={"title": "Work"}).json()
    proposal = client.get(f"/wbs/{root['root_id']}/change-proposals").json()[-1]
    client.post(f"/wbs/change-proposals/{proposal['id']}/decision", json={"decision": "approved"})
    tree = client.get(f"/tasks/{task['id']}/wbs").json()
    node_id = next(node["id"] for node in tree["nodes"] if node["title"] == "Work")
    resource = client.post("/planning-resources", json={"name": "Ada", "weekly_capacity_hours": "8"}).json()
    candidate = client.post("/planning-resources", json={"name": "Grace", "weekly_capacity_hours": "8"}).json()
    client.put(f"/planning-resources/{resource['id']}/weekly-capacity", json={"week_start": "2026-10-12", "capacity_hours": "4"})
    client.put(f"/wbs/{node_id}/weekly-allocations", json={"resource_id": resource["id"], "week_start": "2026-10-12", "planned_hours": "5"})
    client.put(f"/wbs/{node_id}/skill-requirements", json={"name": "python", "minimum_proficiency": 3})
    client.put(f"/planning-resources/{candidate['id']}/skills", json={"name": "python", "proficiency": 5})
    report = client.get(f"/wbs/{root['root_id']}/capacity?week_start=2026-10-12").json()
    assert report["resources"][0]["planned_hours"] == "5"
    assert report["resources"][0]["status"] == "over_capacity"
    assert report["nodes"][0]["skill_status"] == "unknown"
    assert report["suggestions"][0]["resource_id"] == candidate["id"]
    assert {warning["code"] for warning in report["warnings"]} == {"resource_over_capacity", "skill_gap"} or "resource_over_capacity" in {warning["code"] for warning in report["warnings"]}


def _create_atomic_leaf(client, task_title, root_title, leaf_title):
    task = client.post("/tasks", json={"title": task_title, "goal": task_title}).json()
    root = client.post(f"/tasks/{task['id']}/wbs-nodes", json={"title": root_title}).json()
    proposal = client.post(f"/wbs/{root['root_id']}/children", json={"title": leaf_title}).json()
    approved = client.post(
        f"/wbs/change-proposals/{proposal['id']}/decision",
        json={"decision": "approved"},
    )
    assert approved.status_code == 200, approved.text
    tree = client.get(f"/tasks/{task['id']}/wbs").json()
    leaf = next(node for node in tree["nodes"] if node["title"] == leaf_title)
    return task, root, leaf


def _complete_task(client, task_id):
    generated = client.post(
        f"/tasks/{task_id}/generate-plan",
        json={"reason": "Complete capacity exclusion test", "steps": [{"title": "Execute", "objective": "Complete"}]},
    )
    assert generated.status_code == 200, generated.text
    approved = client.post(f"/tasks/{task_id}/approve-plan", json={"decision": "approved"})
    assert approved.status_code == 200, approved.text
    step_id = approved.json()["steps"][0]["id"]
    run = client.post(f"/tasks/{task_id}/steps/{step_id}/runs", json={"executor_type": "human", "input": {}})
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


def test_capacity_aggregates_other_roots_and_prefers_weekly_override(client):
    _, first_root, first_leaf = _create_atomic_leaf(client, "First", "First root", "First work")
    _, second_root, second_leaf = _create_atomic_leaf(client, "Second", "Second root", "Second work")
    resource = client.post(
        "/planning-resources",
        json={"name": "Ada", "weekly_capacity_hours": "10"},
    ).json()

    for node_id, hours in ((first_leaf["id"], "3"), (second_leaf["id"], "4")):
        response = client.put(
            f"/wbs/{node_id}/weekly-allocations",
            json={"resource_id": resource["id"], "week_start": "2026-10-12", "planned_hours": hours},
        )
        assert response.status_code == 200, response.text

    report = client.get(f"/wbs/{first_root['root_id']}/capacity?week_start=2026-10-12").json()
    resource_report = next(item for item in report["resources"] if item["resource_id"] == resource["id"])
    assert resource_report["available_hours"] == "10"
    assert resource_report["planned_hours"] == "7"
    assert resource_report["root_planned_hours"] == "3"
    assert resource_report["other_root_planned_hours"] == "4"
    assert resource_report["utilization_percent"] == "70.00"
    assert resource_report["status"] == "within_capacity"

    override = client.put(
        f"/planning-resources/{resource['id']}/weekly-capacity",
        json={"week_start": "2026-10-12", "capacity_hours": "5"},
    )
    assert override.status_code == 200, override.text
    overridden = client.get(f"/wbs/{second_root['root_id']}/capacity?week_start=2026-10-12").json()
    resource_report = next(item for item in overridden["resources"] if item["resource_id"] == resource["id"])
    assert resource_report["available_hours"] == "5"
    assert resource_report["status"] == "over_capacity"


def test_capacity_distinguishes_unknown_and_explicit_zero(client):
    _, root, leaf = _create_atomic_leaf(client, "Capacity states", "Root", "Work")
    loaded = client.post(
        "/planning-resources",
        json={"name": "Loaded zero", "weekly_capacity_hours": "8"},
    ).json()
    unknown = client.post("/planning-resources", json={"name": "Unknown"}).json()
    zero = client.put(
        f"/planning-resources/{loaded['id']}/weekly-capacity",
        json={"week_start": "2026-10-12", "capacity_hours": "0"},
    )
    assert zero.status_code == 200, zero.text
    allocation = client.put(
        f"/wbs/{leaf['id']}/weekly-allocations",
        json={"resource_id": loaded["id"], "week_start": "2026-10-12", "planned_hours": "1"},
    )
    assert allocation.status_code == 200, allocation.text

    report = client.get(f"/wbs/{root['root_id']}/capacity?week_start=2026-10-12").json()
    by_id = {item["resource_id"]: item for item in report["resources"]}
    assert by_id[loaded["id"]]["status"] == "zero_capacity"
    assert by_id[loaded["id"]]["utilization_percent"] is None
    assert by_id[unknown["id"]]["status"] == "unknown_capacity"
    assert by_id[unknown["id"]]["available_hours"] is None


def test_capacity_upserts_allocation_without_double_counting(client):
    _, root, leaf = _create_atomic_leaf(client, "Upsert", "Root", "Work")
    resource = client.post(
        "/planning-resources",
        json={"name": "Ada", "weekly_capacity_hours": "8"},
    ).json()
    path = f"/wbs/{leaf['id']}/weekly-allocations"
    payload = {"resource_id": resource["id"], "week_start": "2026-10-12", "planned_hours": "2"}
    first = client.put(path, json=payload)
    assert first.status_code == 200, first.text
    second = client.put(path, json={**payload, "planned_hours": "3"})
    assert second.status_code == 200, second.text

    report = client.get(f"/wbs/{root['root_id']}/capacity?week_start=2026-10-12").json()
    resource_report = next(item for item in report["resources"] if item["resource_id"] == resource["id"])
    assert resource_report["planned_hours"] == "3"


def test_candidate_suggestions_require_capacity_after_existing_load(client):
    _, root, target = _create_atomic_leaf(client, "Suggestions", "Root", "Target")
    _, _, other = _create_atomic_leaf(client, "Other", "Other root", "Other work")
    current = client.post(
        "/planning-resources",
        json={"name": "Current", "weekly_capacity_hours": "8"},
    ).json()
    exact = client.post(
        "/planning-resources",
        json={"name": "Exact fit", "weekly_capacity_hours": "8"},
    ).json()
    busy = client.post(
        "/planning-resources",
        json={"name": "Busy", "weekly_capacity_hours": "7"},
    ).json()
    for resource in (exact, busy):
        response = client.put(
            f"/planning-resources/{resource['id']}/skills",
            json={"name": "python", "proficiency": 5},
        )
        assert response.status_code == 200, response.text
    assert client.put(
        f"/wbs/{target['id']}/skill-requirements",
        json={"name": "python", "minimum_proficiency": 3},
    ).status_code == 200
    assert client.put(
        f"/wbs/{target['id']}/weekly-allocations",
        json={"resource_id": current["id"], "week_start": "2026-10-12", "planned_hours": "3"},
    ).status_code == 200
    for resource, hours in ((exact, "5"), (busy, "5")):
        assert client.put(
            f"/wbs/{other['id']}/weekly-allocations",
            json={"resource_id": resource["id"], "week_start": "2026-10-12", "planned_hours": hours},
        ).status_code == 200

    report = client.get(f"/wbs/{root['root_id']}/capacity?week_start=2026-10-12").json()
    suggestions = {item["resource_id"] for item in report["suggestions"]}
    assert exact["id"] in suggestions
    assert busy["id"] not in suggestions


def test_capacity_excludes_cancelled_other_root_load(client):
    _, first_root, first_leaf = _create_atomic_leaf(client, "First active", "First root", "First work")
    second_task, _, second_leaf = _create_atomic_leaf(client, "Second cancelled", "Second root", "Second work")
    resource = client.post(
        "/planning-resources",
        json={"name": "Ada", "weekly_capacity_hours": "8"},
    ).json()
    allocation = client.put(
        f"/wbs/{second_leaf['id']}/weekly-allocations",
        json={"resource_id": resource["id"], "week_start": "2026-10-12", "planned_hours": "4"},
    )
    assert allocation.status_code == 200, allocation.text
    closed = client.post(f"/tasks/{second_task['id']}/close", json={"reason": "Cancelled for capacity test"})
    assert closed.status_code == 200, closed.text

    report = client.get(f"/wbs/{first_root['root_id']}/capacity?week_start=2026-10-12").json()
    resource_report = next(item for item in report["resources"] if item["resource_id"] == resource["id"])
    assert resource_report["planned_hours"] == "0"
    assert resource_report["other_root_planned_hours"] == "0"
    assert report["nodes"][0]["node_id"] == first_leaf["id"]


def test_capacity_reports_skill_gap_and_missing_profile(client):
    _, gap_root, gap_leaf = _create_atomic_leaf(client, "Skill gap", "Gap root", "Gap work")
    _, unknown_root, unknown_leaf = _create_atomic_leaf(client, "Skill unknown", "Unknown root", "Unknown work")
    low_skill = client.post(
        "/planning-resources",
        json={"name": "Low skill", "weekly_capacity_hours": "8"},
    ).json()
    missing_profile = client.post(
        "/planning-resources",
        json={"name": "Missing profile", "weekly_capacity_hours": "8"},
    ).json()
    for node_id in (gap_leaf["id"], unknown_leaf["id"]):
        response = client.put(
            f"/wbs/{node_id}/skill-requirements",
            json={"name": "python", "minimum_proficiency": 3},
        )
        assert response.status_code == 200, response.text
    assert client.put(
        f"/planning-resources/{low_skill['id']}/skills",
        json={"name": "python", "proficiency": 2},
    ).status_code == 200
    assert client.put(
        f"/wbs/{gap_leaf['id']}/weekly-allocations",
        json={"resource_id": low_skill["id"], "week_start": "2026-10-12", "planned_hours": "1"},
    ).status_code == 200
    assert client.put(
        f"/wbs/{unknown_leaf['id']}/weekly-allocations",
        json={"resource_id": missing_profile["id"], "week_start": "2026-10-12", "planned_hours": "1"},
    ).status_code == 200

    gap_report = client.get(f"/wbs/{gap_root['root_id']}/capacity?week_start=2026-10-12").json()
    unknown_report = client.get(f"/wbs/{unknown_root['root_id']}/capacity?week_start=2026-10-12").json()
    assert gap_report["nodes"][0]["skill_status"] == "gap"
    assert any(warning["code"] == "skill_gap" for warning in gap_report["warnings"])
    assert unknown_report["nodes"][0]["skill_status"] == "unknown"
    assert not any(warning["code"] == "skill_gap" for warning in unknown_report["warnings"])


def test_capacity_rejects_non_atomic_allocation_and_excludes_completed_work(client):
    task = client.post("/tasks", json={"title": "Completed root", "goal": "Completed root"}).json()
    execution_task = client.post("/tasks", json={"title": "Completed work", "goal": "Completed work"}).json()
    root = client.post(f"/tasks/{task['id']}/wbs-nodes", json={"title": "Root"}).json()
    proposal = client.post(
        f"/wbs/{root['root_id']}/children",
        json={"title": "Work", "execution_task_id": execution_task["id"]},
    ).json()
    approved = client.post(
        f"/wbs/change-proposals/{proposal['id']}/decision",
        json={"decision": "approved"},
    )
    assert approved.status_code == 200, approved.text
    tree = client.get(f"/tasks/{task['id']}/wbs").json()
    leaf = next(node for node in tree["nodes"] if node["title"] == "Work")
    resource = client.post(
        "/planning-resources",
        json={"name": "Ada", "weekly_capacity_hours": "8"},
    ).json()
    rejected = client.put(
        f"/wbs/{root['root_id']}/weekly-allocations",
        json={"resource_id": resource["id"], "week_start": "2026-10-12", "planned_hours": "2"},
    )
    assert rejected.status_code == 422

    assert client.put(
        f"/wbs/{leaf['id']}/weekly-allocations",
        json={"resource_id": resource["id"], "week_start": "2026-10-12", "planned_hours": "2"},
    ).status_code == 200
    _complete_task(client, execution_task["id"])
    report = client.get(f"/wbs/{root['root_id']}/capacity?week_start=2026-10-12").json()
    resource_report = next(item for item in report["resources"] if item["resource_id"] == resource["id"])
    assert resource_report["planned_hours"] == "0"
    assert report["nodes"] == []


def test_capacity_get_is_read_only_for_wbs_and_timeline(client):
    task, root, leaf = _create_atomic_leaf(client, "Read only", "Root", "Work")
    resource = client.post(
        "/planning-resources",
        json={"name": "Ada", "weekly_capacity_hours": "8"},
    ).json()
    assert client.put(
        f"/wbs/{leaf['id']}/weekly-allocations",
        json={"resource_id": resource["id"], "week_start": "2026-10-12", "planned_hours": "1"},
    ).status_code == 200
    before_tree = client.get(f"/tasks/{task['id']}/wbs").json()
    before_timeline = client.get(f"/tasks/{task['id']}/timeline").json()

    response = client.get(f"/wbs/{root['root_id']}/capacity?week_start=2026-10-12")
    assert response.status_code == 200, response.text

    assert client.get(f"/tasks/{task['id']}/wbs").json() == before_tree
    assert client.get(f"/tasks/{task['id']}/timeline").json() == before_timeline


def test_capacity_schema_upgrade_is_idempotent(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, inspect, text

    from app import db as db_module
    from app.db import Base

    database_path = tmp_path / "capacity-legacy.db"
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title VARCHAR(255) NOT NULL, goal TEXT NOT NULL, status VARCHAR(50) NOT NULL)"))
        connection.execute(text("CREATE TABLE task_steps (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, title VARCHAR(255) NOT NULL, objective TEXT NOT NULL, status VARCHAR(50) NOT NULL, position INTEGER NOT NULL)"))
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "DATABASE_URL", f"sqlite:///{database_path}")

    db_module.ensure_sqlite_schema()
    db_module.ensure_sqlite_schema()

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "planning_resources",
        "resource_skills",
        "resource_week_capacities",
        "wbs_skill_requirements",
        "wbs_week_allocations",
    }.issubset(tables)
    allocation_indexes = {index["name"] for index in inspector.get_indexes("wbs_week_allocations")}
    assert "ix_wbs_week_allocations_week_resource" in allocation_indexes


def test_capacity_input_boundaries_and_invalid_resource_references(client):
    from decimal import Decimal

    from app.services.resource_capacity_service import hours_to_minutes

    assert hours_to_minutes(Decimal("0.00834")) == 1

    negative_resource = client.post(
        "/planning-resources",
        json={"name": "Negative", "weekly_capacity_hours": "-1"},
    )
    assert negative_resource.status_code == 422
    infinite_resource = client.post(
        "/planning-resources",
        json={"name": "Infinite", "weekly_capacity_hours": "Infinity"},
    )
    assert infinite_resource.status_code == 422

    _, root, leaf = _create_atomic_leaf(client, "Invalid inputs", "Root", "Work")
    missing_skill = client.put(
        "/planning-resources/999999/skills",
        json={"name": "python", "proficiency": 3},
    )
    assert missing_skill.status_code == 404
    missing_capacity = client.put(
        "/planning-resources/999999/weekly-capacity",
        json={"week_start": "2026-10-12", "capacity_hours": "4"},
    )
    assert missing_capacity.status_code == 404
    missing_allocation_resource = client.put(
        f"/wbs/{leaf['id']}/weekly-allocations",
        json={"resource_id": 999999, "week_start": "2026-10-12", "planned_hours": "1"},
    )
    assert missing_allocation_resource.status_code == 404
    invalid_requirement = client.put(
        f"/wbs/{leaf['id']}/skill-requirements",
        json={"name": "python", "minimum_proficiency": 6},
    )
    assert invalid_requirement.status_code == 422


def test_capacity_week_requires_monday(client):
    response = client.get("/wbs/999/capacity?week_start=2026-10-13")
    assert response.status_code == 422


def test_capacity_planning_records_can_be_revoked(client):
    task, root, leaf = _create_atomic_leaf(client, "Revoke records", "Root", "Work")
    resource = client.post(
        "/planning-resources",
        json={"name": "Ada", "weekly_capacity_hours": "8"},
    ).json()
    week_start = "2026-10-19"
    assert client.put(
        f"/planning-resources/{resource['id']}/skills",
        json={"name": "python", "proficiency": 2},
    ).status_code == 200
    assert client.put(
        f"/planning-resources/{resource['id']}/weekly-capacity",
        json={"week_start": week_start, "capacity_hours": "4"},
    ).status_code == 200
    assert client.put(
        f"/wbs/{leaf['id']}/skill-requirements",
        json={"name": "python", "minimum_proficiency": 3},
    ).status_code == 200
    assert client.put(
        f"/wbs/{leaf['id']}/weekly-allocations",
        json={"resource_id": resource["id"], "week_start": week_start, "planned_hours": "5"},
    ).status_code == 200

    before_tree = client.get(f"/tasks/{task['id']}/wbs").json()
    before_timeline = client.get(f"/tasks/{task['id']}/timeline").json()
    capacity = client.get(f"/wbs/{root['root_id']}/capacity?week_start={week_start}").json()
    assert capacity["resources"][0]["status"] == "over_capacity"
    assert capacity["nodes"][0]["skill_status"] == "gap"

    delete_urls = [
        f"/planning-resources/{resource['id']}/skills?name=python",
        f"/planning-resources/{resource['id']}/weekly-capacity?week_start={week_start}",
        f"/wbs/{leaf['id']}/skill-requirements?name=python",
        f"/wbs/{leaf['id']}/weekly-allocations?resource_id={resource['id']}&week_start={week_start}",
    ]
    for url in delete_urls:
        assert client.delete(url).status_code == 200
        assert client.delete(url).status_code == 404

    after = client.get(f"/wbs/{root['root_id']}/capacity?week_start={week_start}").json()
    assert after["resources"][0]["available_hours"] == "8"
    assert after["resources"][0]["planned_hours"] == "0"
    assert after["nodes"][0]["skill_status"] == "not_required"
    assert client.get(f"/tasks/{task['id']}/wbs").json() == before_tree
    assert client.get(f"/tasks/{task['id']}/timeline").json() == before_timeline


def test_deleting_resource_removes_associated_planning_data(client):
    first_task, first_root, first_leaf = _create_atomic_leaf(client, "Resource owner", "First root", "First work")
    _, _, other_leaf = _create_atomic_leaf(client, "Other root", "Other root", "Other work")
    resource = client.post(
        "/planning-resources",
        json={"name": "Ada", "weekly_capacity_hours": "8"},
    ).json()
    week_start = "2026-10-19"
    assert client.put(
        f"/planning-resources/{resource['id']}/skills",
        json={"name": "python", "proficiency": 5},
    ).status_code == 200
    assert client.put(
        f"/planning-resources/{resource['id']}/weekly-capacity",
        json={"week_start": week_start, "capacity_hours": "6"},
    ).status_code == 200
    for node in (first_leaf, other_leaf):
        assert client.put(
            f"/wbs/{node['id']}/weekly-allocations",
            json={"resource_id": resource["id"], "week_start": week_start, "planned_hours": "3"},
        ).status_code == 200

    before_tree = client.get(f"/tasks/{first_task['id']}/wbs").json()
    before_timeline = client.get(f"/tasks/{first_task['id']}/timeline").json()
    response = client.delete(f"/planning-resources/{resource['id']}")
    assert response.status_code == 200
    assert client.delete(f"/planning-resources/{resource['id']}").status_code == 404

    report = client.get(f"/wbs/{first_root['root_id']}/capacity?week_start={week_start}").json()
    assert report["resources"] == []
    assert report["nodes"][0]["planned_hours"] == "0"
    assert client.get(f"/tasks/{first_task['id']}/wbs").json() == before_tree
    assert client.get(f"/tasks/{first_task['id']}/timeline").json() == before_timeline


def test_capacity_put_routes_allow_cors_preflight(client):
    response = client.options(
        "/planning-resources/1/weekly-capacity",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert "PUT" in response.headers["access-control-allow-methods"]
