from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = "sqlite:///./long_task_manager.db"


class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


TASK_COLUMNS = {
    "executor_mode": "VARCHAR(50) NOT NULL DEFAULT 'agent'",
    "project_path": "TEXT",
    "codex_tmux_session": "VARCHAR(255)",
}

PHASE2_STEP_COLUMNS = {
    "comparison_group_id": "INTEGER",
    "depends_on_step_ids": "JSON NOT NULL DEFAULT '[]'",
    "previous_step_ids": "JSON NOT NULL DEFAULT '[]'",
    "next_step_ids": "JSON NOT NULL DEFAULT '[]'",
    "step_order": "INTEGER",
    "is_dynamic": "BOOLEAN NOT NULL DEFAULT 0",
    "created_reason": "TEXT",
    "created_by_type": "VARCHAR(50) NOT NULL DEFAULT 'system'",
    "created_by_id": "VARCHAR(255)",
    "inserted_after_step_id": "INTEGER",
    "supersedes_step_id": "INTEGER",
    "superseded_by_step_id": "INTEGER",
    "executor_hint": "VARCHAR(255)",
    "requires_approval": "BOOLEAN NOT NULL DEFAULT 1",
    "max_attempts": "INTEGER",
    "variant_label": "VARCHAR(255)",
    "selected_variant": "BOOLEAN",
    "is_fork": "BOOLEAN NOT NULL DEFAULT 0",
    "forked_from_step_id": "INTEGER",
    "forked_from_run_id": "INTEGER",
    "fork_reason": "TEXT",
    "branch_status": "VARCHAR(50)",
    "cloned_from_step_id": "INTEGER",
    "clone_batch_id": "VARCHAR(255)",
    "is_selected_variant": "BOOLEAN",
}

PHASE3_COMPARISON_GROUP_COLUMNS = {
    "base_step_id": "INTEGER",
    "title": "VARCHAR(255)",
    "description": "TEXT",
    "status": "VARCHAR(50) NOT NULL DEFAULT 'open'",
    "created_reason": "TEXT",
    "created_by_type": "VARCHAR(50) NOT NULL DEFAULT 'system'",
    "created_by_id": "VARCHAR(255)",
    "resolved_at": "DATETIME",
}
PHASE4_CAPABILITY_INVOCATION_COLUMNS = {
    "capability_name": "VARCHAR(255)",
    "artifacts": "TEXT",
    "completed_at": "DATETIME",
}

WBS_INDEXES = {
    "ix_wbs_nodes_root_parent": "CREATE INDEX IF NOT EXISTS ix_wbs_nodes_root_parent ON wbs_nodes (root_id, parent_id, position, id)",
    "ix_wbs_milestones_node": "CREATE INDEX IF NOT EXISTS ix_wbs_milestones_node ON wbs_milestones (node_id)",
    "ix_wbs_dependencies_predecessor": "CREATE INDEX IF NOT EXISTS ix_wbs_dependencies_predecessor ON wbs_dependencies (predecessor_id)",
    "ix_wbs_dependencies_successor": "CREATE INDEX IF NOT EXISTS ix_wbs_dependencies_successor ON wbs_dependencies (successor_id)",
    "ix_wbs_change_proposals_root_status": "CREATE INDEX IF NOT EXISTS ix_wbs_change_proposals_root_status ON wbs_change_proposals (root_id, status, id)",
}


def ensure_sqlite_schema() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as connection:
        task_rows = connection.execute(text("PRAGMA table_info(tasks)")).mappings().all()
        if task_rows:
            existing_task = {row["name"] for row in task_rows}
            for column, definition in TASK_COLUMNS.items():
                if column not in existing_task:
                    connection.execute(text(f"ALTER TABLE tasks ADD COLUMN {column} {definition}"))

        rows = connection.execute(text("PRAGMA table_info(task_steps)")).mappings().all()
        if not rows:
            return
        existing = {row["name"] for row in rows}
        for column, definition in PHASE2_STEP_COLUMNS.items():
            if column not in existing:
                connection.execute(text(f"ALTER TABLE task_steps ADD COLUMN {column} {definition}"))
        if "step_order" not in existing:
            connection.execute(text("UPDATE task_steps SET step_order = position WHERE step_order IS NULL"))

        group_rows = connection.execute(text("PRAGMA table_info(step_comparison_groups)")).mappings().all()
        if group_rows:
            existing_group = {row["name"] for row in group_rows}
            for column, definition in PHASE3_COMPARISON_GROUP_COLUMNS.items():
                if column not in existing_group:
                    connection.execute(text(f"ALTER TABLE step_comparison_groups ADD COLUMN {column} {definition}"))
            if "base_step_id" not in existing_group and "origin_step_id" in existing_group:
                connection.execute(text("UPDATE step_comparison_groups SET base_step_id = origin_step_id WHERE base_step_id IS NULL"))
            if "status" not in existing_group and "selection_status" in existing_group:
                connection.execute(text("UPDATE step_comparison_groups SET status = selection_status"))
        invocation_rows = connection.execute(text("PRAGMA table_info(capability_invocations)")).mappings().all()
        if invocation_rows:
            existing_invocation = {row["name"] for row in invocation_rows}
            for column, definition in PHASE4_CAPABILITY_INVOCATION_COLUMNS.items():
                if column not in existing_invocation:
                    connection.execute(text(f"ALTER TABLE capability_invocations ADD COLUMN {column} {definition}"))
        for statement in WBS_INDEXES.values():
            connection.execute(text(statement))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
