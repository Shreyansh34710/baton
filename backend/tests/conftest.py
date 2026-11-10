"""Isolated SQLite-backed API test client."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import session as db_session
from app.main import app
from app.api.routes import projects as projects_route


@pytest.fixture
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "baton-test.db"
    engine = create_engine(
        "sqlite:///{}".format(database_path), connect_args={"check_same_thread": False}
    )
    testing_sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", testing_sessions)
    monkeypatch.setattr(projects_route, "run_analysis", lambda _analysis_id: None)
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()
