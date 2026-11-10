"""Milestone 1 health endpoint regression test."""


def test_health_check_returns_api_and_database_status(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
