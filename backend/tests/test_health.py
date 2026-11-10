"""Milestone 1 health endpoint regression test."""

from app.core.config import get_settings


def test_health_check_returns_api_and_database_status(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_production_frontend_origin_is_allowed_by_cors(client):
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://baton-cbbw.onrender.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://baton-cbbw.onrender.com"


def test_production_origin_is_added_without_dropping_configured_cors_origins(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://custom.example,http://localhost:5173")

    assert get_settings().cors_origins == [
        "https://custom.example",
        "http://localhost:5173",
        "https://baton-cbbw.onrender.com",
    ]
