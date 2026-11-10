"""Persistence and retrieval tests for structured analysis results."""

from datetime import datetime, timezone

from app.db import session as db_session
from app.models import AIEnrichment, AnalysisResult, Evidence


def _submit(client):
    return client.post(
        "/api/v1/projects", json={"repository_url": "https://github.com/example/project"}
    ).json()


def _persist_result(analysis_id, project_id):
    result = {
        "analysis_id": analysis_id,
        "project_id": project_id,
        "findings": [
            {
                "finding_id": "finding-risk", "category": "risk", "title": "Potential risk",
                "description": "An evidence-backed potential risk.", "claim_type": "inference",
                "evidence_status": "partially_verified", "confidence": 0.6,
                "evidence_ids": ["evidence-1"], "recommended_next_action": "Review it.",
            },
            {
                "finding_id": "finding-contributor", "category": "contributor",
                "title": "Contributor activity: dev", "description": "Activity is not ownership.",
                "claim_type": "fact", "evidence_status": "source_verified", "confidence": 0.9,
                "evidence_ids": ["evidence-1"], "recommended_next_action": None,
            },
        ],
        "evidence_references": [{
            "evidence_id": "evidence-1", "evidence_type": "issue",
            "source_identifier": "12", "source_url": "https://github.com/example/project/issues/12",
            "retrieved_at": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
            "repository_commit_sha": None,
        }],
        "first_48_hours_plan": [{
            "task_id": "task-1", "timeframe": "first_2_hours", "title": "Review risk",
            "reason": "Grounded in the captured issue.", "priority": "high",
            "finding_ids": ["finding-risk"], "evidence_ids": ["evidence-1"],
        }],
    }
    with db_session.SessionLocal() as db:
        db.add(AnalysisResult(analysis_id=analysis_id, result=result))
        db.commit()


def test_complete_result_and_category_endpoints_retrieve_persisted_data(client):
    created = _submit(client)
    _persist_result(created["analysis_id"], created["project_id"])

    response = client.get("/api/v1/analyses/{}/results".format(created["analysis_id"]))
    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis_id"] == created["analysis_id"]
    assert payload["evidence_references"][0]["source_url"].endswith("/issues/12")
    assert payload["first_48_hours_plan"][0]["timeframe"] == "first_2_hours"

    findings = client.get(
        "/api/v1/analyses/{}/findings?category=risk".format(created["analysis_id"])
    )
    assert findings.status_code == 200
    assert [item["finding_id"] for item in findings.json()["findings"]] == ["finding-risk"]

    risks = client.get("/api/v1/analyses/{}/risks".format(created["analysis_id"]))
    assert [item["category"] for item in risks.json()["findings"]] == ["risk"]

    contributors = client.get("/api/v1/analyses/{}/contributors".format(created["analysis_id"]))
    assert contributors.json()["contributors"][0]["title"] == "Contributor activity: dev"

    plan = client.get("/api/v1/analyses/{}/plan".format(created["analysis_id"]))
    assert plan.json()["first_48_hours_plan"][0]["task_id"] == "task-1"


def test_analysis_results_unknown_and_not_ready_responses(client):
    missing = client.get("/api/v1/analyses/missing/results")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Analysis not found."}

    created = _submit(client)
    pending = client.get("/api/v1/analyses/{}/results".format(created["analysis_id"]))
    assert pending.status_code == 409
    assert pending.json() == {"detail": "Analysis results are not available yet."}


def test_invalid_finding_category_is_rejected(client):
    created = _submit(client)
    response = client.get(
        "/api/v1/analyses/{}/findings?category=made_up".format(created["analysis_id"])
    )
    assert response.status_code == 422


def test_evidence_detail_returns_stored_content_and_related_findings(client):
    created = _submit(client)
    another = _submit(client)
    _persist_result(created["analysis_id"], created["project_id"])
    with db_session.SessionLocal() as db:
        db.add(Evidence(
            id="evidence-1", project_id=created["project_id"], analysis_id=created["analysis_id"],
            evidence_type="issue", source_identifier="12",
            source_url="https://github.com/example/project/issues/12",
            content='{"title":"A stored issue excerpt"}',
        ))
        db.add(Evidence(
            id="evidence-private-to-another-analysis", project_id=another["project_id"],
            analysis_id=another["analysis_id"], evidence_type="issue", source_identifier="99",
            source_url="https://github.com/example/another/issues/99", content="private to another analysis",
        ))
        db.commit()

    response = client.get("/api/v1/analyses/{}/evidence/evidence-1".format(created["analysis_id"]))
    assert response.status_code == 200
    payload = response.json()
    assert payload["content"] == '{"title":"A stored issue excerpt"}'
    assert payload["related_finding_ids"] == ["finding-risk", "finding-contributor"]

    missing = client.get("/api/v1/analyses/{}/evidence/missing".format(created["analysis_id"]))
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Evidence not found."}

    cross_analysis = client.get("/api/v1/analyses/{}/evidence/evidence-private-to-another-analysis".format(created["analysis_id"]))
    assert cross_analysis.status_code == 404


def test_ai_enrichment_status_and_specialized_endpoints(client):
    created = _submit(client)
    _persist_result(created["analysis_id"], created["project_id"])
    enrichment_item = {
        "enrichment_id": "ai-decision-1", "category": "technical_decision",
        "title": "Possible design rationale", "explanation": "This is an inference for review.",
        "claim_type": "inference", "evidence_status": "partially_verified", "confidence": 0.6,
        "evidence_ids": ["evidence-1"], "related_finding_ids": ["finding-risk"],
        "plan_task_ids": [], "recommended_action": "Ask the maintainer.",
        "human_review_status": "needs_review",
    }
    with db_session.SessionLocal() as db:
        db.add(AIEnrichment(
            analysis_id=created["analysis_id"], status="partial",
            progress=100,
            result={
                "items": [enrichment_item], "generated_item_count": 3,
                "accepted_item_count": 1, "rejected_item_count": 2,
                "rejection_reason_counts": {"missing_required_field": 1, "unsupported_reference": 1},
                "rejection_diagnostics": [
                    {"stage": "schema", "reason": "missing_required_field", "item_index": 0},
                    {"stage": "reference", "reason": "unsupported_reference", "item_index": 2},
                ],
            },
            error_code="ollama_output_partially_rejected",
            error_message="Some AI output was omitted because its schema or references could not be validated.",
        ))
        db.commit()

    lifecycle = client.get("/api/v1/analyses/{}".format(created["analysis_id"]))
    assert lifecycle.json()["ai_enrichment_status"] == "partial"
    assert lifecycle.json()["ai_enrichment_progress"] == 100
    assert lifecycle.json()["ai_enrichment_error"]["code"] == "ollama_output_partially_rejected"

    full = client.get("/api/v1/analyses/{}/ai-enrichment".format(created["analysis_id"]))
    assert full.json()["status"] == "partial"
    assert full.json()["progress"] == 100
    assert full.json()["items"][0]["human_review_status"] == "needs_review"
    assert full.json()["generated_item_count"] == 3
    assert full.json()["accepted_item_count"] == 1
    assert full.json()["rejected_item_count"] == 2
    assert full.json()["rejection_reason_counts"] == {"missing_required_field": 1, "unsupported_reference": 1}
    assert full.json()["rejection_diagnostics"][0]["reason"] == "missing_required_field"

    status_response = client.get("/api/v1/analyses/{}/ai-enrichment/status".format(created["analysis_id"]))
    assert status_response.json()["status"] == "partial"
    assert status_response.json()["rejection_reason_counts"]["unsupported_reference"] == 1
    assert len(status_response.json()["rejection_diagnostics"]) == 2

    decisions = client.get("/api/v1/analyses/{}/decisions".format(created["analysis_id"]))
    assert decisions.json()["items"][0]["category"] == "technical_decision"

    risk_explanations = client.get("/api/v1/analyses/{}/risks/explanations".format(created["analysis_id"]))
    assert risk_explanations.json()["items"] == []

    enriched_plan = client.get("/api/v1/analyses/{}/plan/enriched".format(created["analysis_id"]))
    assert enriched_plan.json()["enrichment_status"] == "partial"
    assert enriched_plan.json()["deterministic_plan"][0]["task_id"] == "task-1"
