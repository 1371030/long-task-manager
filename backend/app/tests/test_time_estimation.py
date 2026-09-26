from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text

from app import models
from app.db import get_db
from app.services.estimate_buffer_service import (
    hours_to_ms,
    normalize_estimate_category,
)


def create_task(client, title: str) -> int:
    response = client.post(
        "/tasks",
        json={"title": title, "goal": f"Complete {title}", "executor_mode": "agent"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def create_root(client, task_id: int, title: str = "Program") -> dict:
    response = client.post(f"/tasks/{task_id}/wbs-nodes", json={"title": title})
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, proposal_id: int) -> None:
    response = client.post(
        f"/wbs/change-proposals/{proposal_id}/decision",
        json={"decision": "approved"},
    )
    assert response.status_code == 200, response.text


def child(client, parent_id: int, task_id: int, title: str, position: int) -> int:
    response = client.post(
        f"/wbs/{parent_id}/children",
        json={"title": title, "execution_task_id": task_id, "position": position},
    )
    assert response.status_code == 200, response.text
    approve(client, response.json()["id"])
    tree = client.get(f"/tasks/{task_id}/wbs").json()
    return next(item["id"] for item in tree["nodes"] if item["execution_task_id"] == task_id)


def dependency(client, root_id: int, predecessor_id: int, successor_id: int) -> None:
    response = client.post(
        f"/wbs/{root_id}/dependencies",
        json={"predecessor_id": predecessor_id, "successor_id": successor_id},
    )
    assert response.status_code == 200, response.text
    approve(client, response.json()["id"])


def revision(client, node_id: int, base: int, category: str | None, values: tuple[str, str, str] | None) -> dict:
    payload = {
        "base_revision": base,
        "estimate_category": category,
        "manual_estimate": None,
        "reason": "test estimate",
        "created_by_id": "tester",
    }
    if values is not None:
        payload["manual_estimate"] = {
            "optimistic": values[0],
            "most_likely": values[1],
            "pessimistic": values[2],
        }
    response = client.post(f"/wbs/{node_id}/estimate-revisions", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def session_for(client):
    generator = client.app.dependency_overrides[get_db]()
    return generator, next(generator)


def add_accepted_sample(db, task_id: int, category: str, duration_ms: int | None, offset: int) -> tuple[int, int]:
    step = models.Step(
        task_id=task_id,
        title=f"Historical {offset}",
        objective="Evidence",
        estimate_category=category,
        status="approved",
        position=offset,
        step_order=offset,
        is_active=True,
    )
    db.add(step)
    db.flush()
    started = datetime(2026, 1, 1) + timedelta(hours=offset)
    run = models.StepRun(
        task_id=task_id,
        step_id=step.id,
        attempt_number=1,
        executor_type="human",
        status="accepted",
        started_at=started,
        submitted_at=started + timedelta(milliseconds=duration_ms or 1000),
        duration_ms=duration_ms,
    )
    db.add(run)
    db.flush()
    step.approved_run_id = run.id
    db.commit()
    return step.id, run.id


def test_category_normalization_and_hour_rounding():
    assert normalize_estimate_category("  ＡＰＩ\t设计  ") == "api-设计"
    assert hours_to_ms(Decimal("0.0000004166666667")) == 2
    with pytest.raises(HTTPException):
        normalize_estimate_category(" \t ")
    with pytest.raises(HTTPException):
        normalize_estimate_category("bad\x00category")
    with pytest.raises(HTTPException):
        normalize_estimate_category("x" * 65)


def test_step_category_normalizes_and_propagates(client):
    task_id = create_task(client, "Categories")
    generated = client.post(
        f"/tasks/{task_id}/generate-plan",
        json={
            "steps": [
                {
                    "title": "Design",
                    "objective": "Design",
                    "estimate_category": " API   Design ",
                }
            ]
        },
    )
    assert generated.status_code == 200, generated.text
    step = generated.json()["steps"][0]
    assert step["estimate_category"] == "api-design"

    updated = client.patch(
        f"/tasks/{task_id}/steps/{step['id']}",
        json={"estimate_category": " 实施 ", "title": None},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["estimate_category"] == "实施"

    forked = client.post(
        f"/tasks/{task_id}/steps/{step['id']}/fork",
        json={"variant_label": "v2", "title": "Fork", "objective": "Fork"},
    )
    assert forked.status_code == 200, forked.text
    steps = client.get(f"/tasks/{task_id}/steps").json()
    fork = next(item for item in steps if item["id"] == forked.json()["forked_step_id"])
    assert fork["estimate_category"] == "实施"


def test_revision_is_immutable_conflict_safe_and_get_is_read_only(client):
    task_id = create_task(client, "Estimate revision")
    root = create_root(client, task_id)
    root_id = root["root_id"]
    structure_version = root["version"]

    first = revision(client, root_id, 0, " API  Design ", ("1", "2", "4"))
    assert first["revision_number"] == 1
    assert first["estimate_category"] == "api-design"
    assert first["optimistic_ms"] == 3_600_000
    assert first["most_likely_ms"] == 7_200_000
    assert first["pessimistic_ms"] == 14_400_000

    conflict = client.post(
        f"/wbs/{root_id}/estimate-revisions",
        json={"base_revision": 0, "estimate_category": "api-design", "manual_estimate": None},
    )
    assert conflict.status_code == 409
    second = revision(client, root_id, 1, "api-design", None)
    assert second["revision_number"] == 2
    assert second["optimistic_ms"] is None

    generator, db = session_for(client)
    try:
        assert db.query(models.WbsEstimateRevision).filter_by(node_id=root_id).count() == 2
        event_count = db.query(models.Event).count()
        root_before = db.get(models.WbsNode, root_id)
        updated_at = root_before.updated_at
    finally:
        generator.close()

    response = client.get(f"/tasks/{task_id}/wbs/estimate-buffer")
    assert response.status_code == 200, response.text
    assert response.json()["wbs_version"] == structure_version
    assert response.json()["node_estimates"][0]["latest_revision"] == 2

    generator, db = session_for(client)
    try:
        assert db.query(models.Event).count() == event_count
        assert db.get(models.WbsNode, root_id).updated_at == updated_at
    finally:
        generator.close()


def test_historical_threshold_quantiles_and_self_task_exclusion(client):
    target_task = create_task(client, "Target")
    root_id = create_root(client, target_task)["root_id"]
    revision(client, root_id, 0, "Build", None)
    history_task = create_task(client, "History")

    generator, db = session_for(client)
    try:
        add_accepted_sample(db, history_task, "build", 1_000, 1)
        add_accepted_sample(db, history_task, "build", 2_000, 2)
    finally:
        generator.close()

    insufficient = client.get(f"/tasks/{target_task}/wbs/estimate-buffer").json()
    estimate = insufficient["node_estimates"][0]
    assert estimate["source"] == "unavailable"
    assert estimate["reason"] == "insufficient_history"
    assert estimate["sample_count"] == 2

    generator, db = session_for(client)
    try:
        add_accepted_sample(db, history_task, "build", 10_000, 3)
        add_accepted_sample(db, target_task, "build", 999_999, 4)
        rejected_step = models.Step(
            task_id=history_task,
            title="Rejected",
            objective="Excluded",
            estimate_category="build",
            status="failed",
            position=9,
            step_order=9,
        )
        db.add(rejected_step)
        db.flush()
        db.add(
            models.StepRun(
                task_id=history_task,
                step_id=rejected_step.id,
                attempt_number=1,
                executor_type="human",
                status="rejected",
                duration_ms=500_000,
            )
        )
        db.commit()
    finally:
        generator.close()

    available = client.get(f"/tasks/{target_task}/wbs/estimate-buffer").json()
    estimate = available["node_estimates"][0]
    assert estimate["source"] == "historical"
    assert estimate["sample_count"] == 3
    assert estimate["optimistic_ms"] == 1_000
    assert estimate["expected_ms"] == 2_000
    assert estimate["conservative_ms"] == 10_000
    assert [item["duration_ms"] for item in estimate["evidence"]] == [1_000, 2_000, 10_000]


def test_final_approved_run_actual_deduplicates_retries(client):
    task_id = create_task(client, "Actual")
    root_id = create_root(client, task_id)["root_id"]
    revision(client, root_id, 0, "work", ("0.5", "1", "2"))

    generator, db = session_for(client)
    try:
        task = db.get(models.Task, task_id)
        task.status = "completed"
        step = models.Step(
            task_id=task_id,
            title="Execute",
            objective="Execute",
            estimate_category="work",
            status="approved",
            position=1,
            step_order=1,
            is_active=True,
        )
        db.add(step)
        db.flush()
        old_run = models.StepRun(
            task_id=task_id,
            step_id=step.id,
            attempt_number=1,
            executor_type="human",
            status="accepted",
            duration_ms=9_000_000,
        )
        final_run = models.StepRun(
            task_id=task_id,
            step_id=step.id,
            attempt_number=2,
            executor_type="human",
            status="accepted",
            duration_ms=4_000_000,
        )
        db.add_all([old_run, final_run])
        db.flush()
        step.approved_run_id = final_run.id
        db.commit()
    finally:
        generator.close()

    response = client.get(f"/tasks/{task_id}/wbs/estimate-buffer")
    assert response.status_code == 200, response.text
    estimate = response.json()["node_estimates"][0]
    assert estimate["actual_ms"] == 4_000_000
    assert estimate["actual_availability"] == "available"


def test_weighted_main_path_feeding_buffer_and_rss(client):
    root_task = create_task(client, "Program")
    a_task = create_task(client, "A")
    b_task = create_task(client, "B")
    c_task = create_task(client, "C")
    root_id = create_root(client, root_task)["root_id"]
    a_id = child(client, root_id, a_task, "A", 1)
    c_id = child(client, root_id, c_task, "C", 2)
    b_id = child(client, root_id, b_task, "B", 3)
    dependency(client, root_id, a_id, b_id)
    dependency(client, root_id, c_id, b_id)

    revision(client, a_id, 0, "a", ("1", "2", "4"))
    revision(client, b_id, 0, "b", ("1", "1", "2"))
    revision(client, c_id, 0, "c", ("1", "1", "1"))

    response = client.get(f"/tasks/{root_task}/wbs/estimate-buffer")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["availability"] == "available"
    assert body["schedule"]["node_ids"] == [a_id, b_id]
    assert body["schedule"]["covered_node_ids"] == [a_id, b_id]
    assert body["schedule"]["expected_ms"] == 12_000_000
    assert body["project_buffer"]["recommended_ms"] == 7_249_828
    assert len(body["feeding_buffers"]) == 1
    assert body["feeding_buffers"][0]["path_node_ids"] == [c_id]
    assert body["feeding_buffers"][0]["join_node_id"] == b_id
    assert body["feeding_buffers"][0]["recommended_ms"] == 0
    assert body["feeding_buffers"][0]["status"] == "not_applicable"


def test_request_rejects_invalid_manual_estimate(client):
    task_id = create_task(client, "Validation")
    root_id = create_root(client, task_id)["root_id"]
    for manual in (
        {"optimistic": "2", "most_likely": "1", "pessimistic": "3"},
        {"optimistic": "-1", "most_likely": "1", "pessimistic": "3"},
        {"optimistic": "NaN", "most_likely": "1", "pessimistic": "3"},
    ):
        response = client.post(
            f"/wbs/{root_id}/estimate-revisions",
            json={"base_revision": 0, "estimate_category": "work", "manual_estimate": manual},
        )
        assert response.status_code == 422


def test_sqlite_estimate_partial_upgrade_is_idempotent(tmp_path, monkeypatch):
    from sqlalchemy import create_engine

    from app import db as db_module
    from app.db import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'estimate-legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title VARCHAR(255) NOT NULL, goal TEXT NOT NULL, status VARCHAR(50) NOT NULL)"))
        connection.execute(text("CREATE TABLE task_steps (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, title VARCHAR(255) NOT NULL, objective TEXT NOT NULL, status VARCHAR(50) NOT NULL, position INTEGER NOT NULL)"))
        connection.execute(text("CREATE TABLE wbs_nodes (id INTEGER PRIMARY KEY, root_id INTEGER, parent_id INTEGER, execution_task_id INTEGER, node_type VARCHAR(50), title VARCHAR(255), position INTEGER, is_active BOOLEAN, version INTEGER)"))
        connection.execute(text("CREATE TABLE wbs_estimate_revisions (id INTEGER PRIMARY KEY, node_id INTEGER NOT NULL)"))
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "DATABASE_URL", f"sqlite:///{tmp_path / 'estimate-legacy.db'}")

    db_module.ensure_sqlite_schema()
    db_module.ensure_sqlite_schema()

    inspector = inspect(engine)
    step_columns = {column["name"] for column in inspector.get_columns("task_steps")}
    revision_columns = {column["name"] for column in inspector.get_columns("wbs_estimate_revisions")}
    assert "estimate_category" in step_columns
    assert set(db_module.ESTIMATE_REVISION_COLUMNS).issubset(revision_columns)
    revision_indexes = {index["name"] for index in inspector.get_indexes("wbs_estimate_revisions")}
    assert "ix_wbs_estimate_revisions_node_revision" in revision_indexes
    assert "uq_wbs_estimate_revision" in revision_indexes


def test_sqlite_estimate_upgrade_indexes_exist(client):
    generator, db = session_for(client)
    try:
        inspector = inspect(db.get_bind())
        assert "wbs_estimate_revisions" in inspector.get_table_names()
        step_indexes = {index["name"] for index in inspector.get_indexes("task_steps")}
        revision_indexes = {index["name"] for index in inspector.get_indexes("wbs_estimate_revisions")}
        assert "ix_task_steps_estimate_category" in step_indexes
        assert "ix_wbs_estimate_revisions_node_revision" in revision_indexes
        columns = {row[1] for row in db.execute(text("PRAGMA table_info(task_steps)"))}
        assert "estimate_category" in columns
    finally:
        generator.close()
