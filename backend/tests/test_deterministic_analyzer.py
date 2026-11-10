"""Deterministic, source-grounded analysis tests using local SQLite evidence."""

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Analysis, Evidence, Project
from app.services.deterministic_analyzer import DeterministicAnalyzer, validate_findings


RETRIEVED = datetime(2026, 1, 31, 12, 0, tzinfo=timezone.utc)


def _factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _add(db, analysis_id, kind, identifier, value, url=None):
    row = Evidence(
        id="evidence-{}-{}".format(kind, identifier.replace("/", "-")),
        project_id="project-1", analysis_id=analysis_id, evidence_type=kind,
        source_identifier=identifier,
        source_url=url or "https://github.com/example/project/" + identifier,
        content=value if isinstance(value, str) else json.dumps(value),
        retrieved_at=RETRIEVED, repository_commit_sha="a" * 40,
    )
    db.add(row)
    db.flush()
    return row


def _corpus(factory):
    with factory() as db:
        project = Project(id="project-1", repository_url="https://github.com/example/project")
        analysis = Analysis(
            id="analysis-1", project_id=project.id, status="running", progress=96,
            current_stage="Analyzing repository evidence",
        )
        db.add_all([project, analysis])
        _add(db, analysis.id, "repository", "repository", {
            "full_name": "example/project", "description": "A service example",
            "default_branch": "main", "updated_at": "2026-01-30T00:00:00Z",
        })
        _add(db, analysis.id, "readme", "README", """# Example

A sample service for teams.

Install dependencies with pip. The project supports request validation.

Future work: add an admin panel.
""")
        _add(db, analysis.id, "tree", "tree", [
            {"path": "README.md", "type": "blob"},
            {"path": "app.py", "type": "blob"},
            {"path": "tests/test_app.py", "type": "blob"},
            {"path": "docs/architecture.md", "type": "blob"},
        ])
        _add(db, analysis.id, "source_file", "app.py", """# TODO: add retry handling
def serve():
    pass  # FIXME: catch errors
""")
        _add(db, analysis.id, "commit", "b" * 40, {
            "sha": "b" * 40,
            "message": "feat: add request validation\n\nDecision: We chose a small local parser.",
            "author": {"name": "A", "date": "2026-01-29T10:00:00Z"},
        })
        _add(db, analysis.id, "issue", "1", {
            "number": 1, "title": "Old bug", "state": "closed", "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z", "labels": ["bug"], "assignees": ["dev"],
        })
        _add(db, analysis.id, "issue", "2", {
            "number": 2, "title": "Investigate timeout", "state": "open",
            "created_at": "2025-01-20T00:00:00Z", "updated_at": "2026-01-29T00:00:00Z",
            "labels": ["blocker"], "assignees": [],
        })
        _add(db, analysis.id, "pull_request", "3", {
            "number": 3, "title": "Add parser", "state": "closed", "merged_at": "2026-01-25T00:00:00Z",
            "created_at": "2026-01-20T00:00:00Z", "updated_at": "2026-01-25T00:00:00Z",
            "user": "alice", "assignees": ["alice"], "body": "We decided to use a local parser.",
        })
        _add(db, analysis.id, "pull_request", "4", {
            "number": 4, "title": "Draft cache", "state": "open", "merged_at": None,
            "created_at": "2025-12-01T00:00:00Z", "updated_at": "2025-12-15T00:00:00Z",
            "user": "bob", "assignees": [],
        })
        for login, count in (("alice", 18), ("bob", 2), ("carol", 1)):
            _add(db, analysis.id, "contributor", login, {"login": login, "contributions": count})
        db.commit()


def test_analysis_covers_categories_and_cites_only_existing_evidence():
    engine, factory = _factory()
    _corpus(factory)
    with factory() as db:
        analyzer = DeterministicAnalyzer()
        result = analyzer.analyze("analysis-1", db)
        evidence_ids = {item["evidence_id"] for item in result["evidence_references"]}
        categories = {item["category"] for item in result["findings"]}
        assert categories == {
            "overview", "completed", "ongoing", "unfinished", "technical_decision",
            "contributor", "risk", "knowledge_gap",
        }
        assert all(set(item["evidence_ids"]).issubset(evidence_ids) for item in result["findings"])
        assert all(item["claim_type"] not in {"fact", "inference"} or item["evidence_ids"] for item in result["findings"])
        verified = next(item for item in result["findings"] if item["title"].startswith("Issue #1 closed"))
        inferred = next(item for item in result["findings"] if item["title"] == "Primary technologies")
        assert (verified["claim_type"], verified["evidence_status"], verified["confidence"]) == (
            "fact", "source_verified", 0.84,
        )
        assert inferred["claim_type"] == "inference"
        assert inferred["evidence_status"] == "partially_verified"
        assert 0 < inferred["confidence"] < verified["confidence"]
        assert all(set(task["finding_ids"]).issubset({f["finding_id"] for f in result["findings"]}) for task in result["first_48_hours_plan"])
        assert all(set(task["evidence_ids"]).issubset(evidence_ids) for task in result["first_48_hours_plan"])
        assert {task["timeframe"] for task in result["first_48_hours_plan"]} == {
            "first_2_hours", "first_8_hours", "first_24_hours", "first_48_hours",
        }
        assert result == analyzer.analyze("analysis-1", db)
    engine.dispose()


def test_closure_and_merge_are_recorded_without_claiming_feature_completion():
    engine, factory = _factory()
    _corpus(factory)
    with factory() as db:
        result = DeterministicAnalyzer().analyze("analysis-1", db)
        completion = [item for item in result["findings"] if item["category"] == "completed"]
        assert any("Issue #1 closed" in item["title"] for item in completion)
        assert any("Pull request #3 merged" in item["title"] for item in completion)
        assert all("not" in item["description"] for item in completion)
    engine.dispose()


def test_open_work_todo_decision_contributor_and_risk_classifications():
    engine, factory = _factory()
    _corpus(factory)
    with factory() as db:
        findings = DeterministicAnalyzer().analyze("analysis-1", db)["findings"]
        assert any(item["category"] == "ongoing" and "Recently active issue #2" in item["title"] for item in findings)
        assert any(item["category"] == "unfinished" and "TODO/FIXME markers" in item["title"] for item in findings)
        assert any(item["category"] == "technical_decision" for item in findings)
        alice = next(item for item in findings if item["category"] == "contributor" and "alice" in item["title"])
        assert "not proof of component ownership" in alice["description"]
        assert any(item["category"] == "risk" and "Long-standing open issue" in item["title"] for item in findings)
        assert any(item["category"] == "risk" and "concentrated" in item["title"] for item in findings)
        assert any(item["category"] == "knowledge_gap" and "Ownership is unclear" in item["title"] for item in findings)
    engine.dispose()


def test_unsupported_claim_is_downgraded_and_invalid_evidence_id_removed():
    item = {
        "finding_id": "finding-x", "category": "overview", "title": "Unsupported assertion",
        "description": "The project uses an unsupported service.", "claim_type": "fact",
        "evidence_status": "source_verified", "confidence": 0.95,
        "evidence_ids": ["fabricated-id"], "recommended_next_action": None,
    }
    result = validate_findings([item], {"real-id"})[0]
    assert result["claim_type"] == "unknown"
    assert result["evidence_status"] == "insufficient"
    assert result["confidence"] == 0
    assert result["evidence_ids"] == []
    assert "does not establish" in result["description"]
    assert "fabricated-id" not in json.dumps(result)


def test_absent_or_truncated_evidence_produces_unknowns_not_invented_facts():
    engine, factory = _factory()
    with factory() as db:
        project = Project(id="project-1", repository_url="https://github.com/example/project")
        analysis = Analysis(id="analysis-1", project_id=project.id, status="running")
        db.add_all([project, analysis])
        _add(db, analysis.id, "tree", "tree", {"truncated": True, "excerpt": ""})
        db.commit()
        result = DeterministicAnalyzer().analyze("analysis-1", db)
        purpose = next(item for item in result["findings"] if item["title"] == "Project purpose is not established")
        assert purpose["claim_type"] == "unknown"
        assert purpose["evidence_status"] == "insufficient"
        assert not any(item["title"] == "No tests appear in the captured tree" for item in result["findings"])
    engine.dispose()


def test_complete_tree_without_readme_creates_a_supported_documentation_gap():
    engine, factory = _factory()
    with factory() as db:
        project = Project(id="project-1", repository_url="https://github.com/example/project")
        analysis = Analysis(id="analysis-1", project_id=project.id, status="running")
        db.add_all([project, analysis])
        _add(db, analysis.id, "tree", "tree", [{"path": "app.py", "type": "blob"}])
        db.commit()
        findings = DeterministicAnalyzer().analyze("analysis-1", db)["findings"]
        gap = next(item for item in findings if item["title"] == "Project purpose and setup documentation are missing")
        assert gap["claim_type"] == "inference"
        assert gap["evidence_ids"]
    engine.dispose()


def test_empty_repository_tree_does_not_claim_missing_tests_or_unknown_tech_as_fact():
    engine, factory = _factory()
    with factory() as db:
        project = Project(id="project-1", repository_url="https://github.com/example/empty")
        analysis = Analysis(id="analysis-1", project_id=project.id, status="running")
        db.add_all([project, analysis])
        _add(db, analysis.id, "repository", "repository", {"full_name": "example/empty", "default_branch": None})
        _add(db, analysis.id, "tree", "tree:uninitialized", {"available": False, "entries": [], "truncated": False})
        db.commit()
        findings = DeterministicAnalyzer().analyze("analysis-1", db)["findings"]
        technology = next(item for item in findings if item["title"] == "Primary technologies are unknown")
        assert technology["claim_type"] == "unknown"
        assert technology["evidence_status"] == "insufficient"
        assert not any(item["title"] == "No tests appear in the captured tree" for item in findings)
    engine.dispose()
