import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.db import Base, get_db
from app.main import app
from app.services import codex_execution_service, step_execution_service


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    original_step_session_local = step_execution_service.SessionLocal
    original_codex_session_local = codex_execution_service.SessionLocal
    step_execution_service.SessionLocal = TestingSessionLocal
    codex_execution_service.SessionLocal = TestingSessionLocal
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    step_execution_service.SessionLocal = original_step_session_local
    codex_execution_service.SessionLocal = original_codex_session_local
    app.dependency_overrides.clear()
