"""Project creation and analysis lifecycle API tests."""

from sqlalchemy import select

from app.api.routes import projects as projects_route
from app.db import session as db_session
from app.models import Analysis, Project


def test_valid_repository_submission_creates_project_and_queued_analysis(client):
    response = client.post(
        "/api/v1/projects",
        json={"repository_url": "https://github.com/example/project"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["project_id"]
    assert payload["analysis_id"]
    assert payload["status"] == "queued"


def test_repository_submission_schedules_background_ingestion(client, monkeypatch):
    scheduled = []
    monkeypatch.setattr(projects_route, "run_analysis", scheduled.append)
    response = client.post(
        "/api/v1/projects", json={"repository_url": "https://github.com/example/project"}
    )
    assert response.status_code == 201
    assert scheduled == [response.json()["analysis_id"]]


def test_invalid_repository_url_is_rejected(client):
    response = client.post(
        "/api/v1/projects", json={"repository_url": "https://example.com/owner/repository"}
    )

    assert response.status_code == 422
    assert "GitHub repository URL" in response.json()["detail"][0]["msg"]


def test_project_and_analysis_are_persisted_with_relationship(client):
    created = client.post(
        "/api/v1/projects", json={"repository_url": "https://github.com/example/project/"}
    ).json()

    with db_session.SessionLocal() as db:
        project = db.get(Project, created["project_id"])
        analysis = db.get(Analysis, created["analysis_id"])
        assert project is not None
        assert project.repository_url == "https://github.com/example/project"
        assert analysis is not None
        assert analysis.project_id == project.id
        assert analysis.status == "queued"
        assert project.analyses[0].id == analysis.id


def test_analysis_status_is_retrievable(client):
    created = client.post(
        "/api/v1/projects", json={"repository_url": "https://github.com/example/project"}
    ).json()

    response = client.get("/api/v1/analyses/{}".format(created["analysis_id"]))

    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis_id"] == created["analysis_id"]
    assert payload["project_id"] == created["project_id"]
    assert payload["status"] == "queued"
    assert payload["progress"] == 0
    assert payload["current_stage"] == "queued"
    assert payload["created_at"]
    assert payload["updated_at"]
    assert payload["started_at"] is None
    assert payload["completed_at"] is None
    assert payload["error_details"] is None
    assert payload["ai_enrichment_status"] == "not_started"
    assert payload["ai_enrichment_error"] is None


def test_unknown_analysis_returns_404(client):
    response = client.get("/api/v1/analyses/missing-analysis")
    assert response.status_code == 404
    assert response.json() == {"detail": "Analysis not found."}


def test_failed_analysis_returns_error_details(client):
    created = client.post(
        "/api/v1/projects", json={"repository_url": "https://github.com/example/project"}
    ).json()
    with db_session.SessionLocal() as db:
        analysis = db.get(Analysis, created["analysis_id"])
        analysis.status = "failed"
        analysis.progress = 45
        analysis.current_stage = "Ingestion failed"
        analysis.error_code = "github_rate_limited"
        analysis.error_message = "GitHub's public API rate limit was reached. Please retry later."
        db.commit()

    response = client.get("/api/v1/analyses/{}".format(created["analysis_id"]))

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_details"] == {
        "code": "github_rate_limited",
        "message": "GitHub's public API rate limit was reached. Please retry later.",
    }
