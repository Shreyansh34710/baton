"""Analysis lifecycle integration tests with a fully mocked ingestion service."""

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import AIEnrichment, Analysis, AnalysisResult, Evidence, Project
from app.services.analysis_runner import recover_interrupted_analyses, run_analysis
from app.services.github_client import GitHubRateLimited
from app.services.deterministic_analyzer import DeterministicAnalyzer
from app.services.github_ingestion import EvidenceDraft
from app.services.ollama_client import OllamaUnavailable


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _create_queued(factory):
    with factory() as db:
        project = Project(id="project-1", repository_url="https://github.com/example/project")
        analysis = Analysis(id="analysis-1", project_id=project.id, status="queued", progress=0, current_stage="queued")
        db.add_all([project, analysis])
        db.commit()


def test_successful_ingestion_persists_evidence_and_completes():
    engine, factory = _session_factory()
    _create_queued(factory)
    observed = []

    class FakeIngestion:
        def collect(self, repository_url, progress):
            assert repository_url == "https://github.com/example/project"
            progress("Reading repository structure", 20)
            with factory() as db:
                row = db.get(Analysis, "analysis-1")
                observed.append((row.status, row.current_stage, row.progress))
            progress("Collecting commits", 45)
            return [EvidenceDraft(
                "readme", "README", "https://github.com/example/project/blob/main/README.md",
                "Public README content", "a" * 40, datetime.now(timezone.utc),
            )]

        def close(self):
            pass

    class ObservedAnalyzer:
        def analyze(self, analysis_id, db):
            with factory() as check_db:
                row = check_db.get(Analysis, analysis_id)
                observed.append((row.status, row.current_stage, row.progress))
            return DeterministicAnalyzer().analyze(analysis_id, db)

    class SuccessfulEnrichment:
        def enrich(self, _analysis_id, _result, _db, progress):
            progress("Validating AI evidence references", 99)
            return {"status": "completed", "items": [], "rejected_item_count": 0, "error_message": None}

        def close(self):
            pass

    run_analysis(
        "analysis-1", session_factory=factory, ingestion_factory=FakeIngestion,
        analyzer_factory=ObservedAnalyzer, enrichment_factory=SuccessfulEnrichment,
    )
    with factory() as db:
        analysis = db.get(Analysis, "analysis-1")
        records = db.scalars(select(Evidence).where(Evidence.analysis_id == analysis.id)).all()
        saved_result = db.get(AnalysisResult, analysis.id)
        enrichment = db.get(AIEnrichment, analysis.id)
        assert analysis.status == "completed"
        assert analysis.progress == 100
        assert analysis.current_stage == "Analysis complete"
        assert analysis.started_at is not None
        assert analysis.completed_at is not None
        assert len(records) == 1
        assert saved_result is not None
        assert enrichment is not None and enrichment.status == "completed"
        assert enrichment.progress == 100
        assert saved_result.result["analysis_id"] == analysis.id
        assert any(item["category"] == "overview" for item in saved_result.result["findings"])
        assert records[0].project_id == "project-1"
        assert records[0].repository_commit_sha == "a" * 40
        assert records[0].content == "Public README content"
    assert observed == [
        ("running", "Reading repository structure", 20),
        ("running", "Analyzing repository evidence", 96),
    ]
    engine.dispose()


def test_analysis_failure_preserves_ingested_evidence():
    engine, factory = _session_factory()
    _create_queued(factory)

    class SuccessfulIngestion:
        def collect(self, _repository_url, progress):
            progress("Saving repository evidence", 95)
            return [EvidenceDraft(
                "readme", "README", "https://github.com/example/project/blob/main/README.md",
                "Evidence remains even if analysis fails.", "a" * 40,
            )]

        def close(self):
            pass

    class BrokenAnalyzer:
        def analyze(self, _analysis_id, _db):
            raise RuntimeError("private analyzer error")

    run_analysis(
        "analysis-1", session_factory=factory, ingestion_factory=SuccessfulIngestion,
        analyzer_factory=BrokenAnalyzer,
    )
    with factory() as db:
        analysis = db.get(Analysis, "analysis-1")
        records = db.scalars(select(Evidence).where(Evidence.analysis_id == analysis.id)).all()
        assert analysis.status == "failed"
        assert analysis.error_code == "analysis_failed"
        assert "private analyzer error" not in analysis.error_message
        assert len(records) == 1
        assert db.get(AnalysisResult, analysis.id) is None
    engine.dispose()


def test_ollama_failure_keeps_deterministic_analysis_as_partial_success():
    engine, factory = _session_factory()
    _create_queued(factory)

    class SuccessfulIngestion:
        def collect(self, _repository_url, _progress):
            return [EvidenceDraft(
                "readme", "README", "https://github.com/example/project/blob/main/README.md",
                "A retained README excerpt.", "a" * 40,
            )]

        def close(self):
            pass

    class UnavailableEnrichment:
        def enrich(self, *_args):
            raise OllamaUnavailable("private endpoint or response detail")

        def close(self):
            pass

    run_analysis(
        "analysis-1", session_factory=factory, ingestion_factory=SuccessfulIngestion,
        enrichment_factory=UnavailableEnrichment,
    )
    with factory() as db:
        analysis = db.get(Analysis, "analysis-1")
        result = db.get(AnalysisResult, analysis.id)
        enrichment = db.get(AIEnrichment, analysis.id)
        records = db.scalars(select(Evidence).where(Evidence.analysis_id == analysis.id)).all()
        assert analysis.status == "completed"
        assert analysis.progress == 100
        assert analysis.current_stage == "Deterministic analysis complete; AI unavailable"
        assert analysis.error_code is None
        assert result is not None
        assert records
        assert enrichment.status == "failed"
        assert enrichment.progress < 100
        assert enrichment.error_code == "ollama_unavailable"
        assert enrichment.error_message == OllamaUnavailable.safe_message
        assert "private endpoint" not in enrichment.error_message
    engine.dispose()


def test_rate_limit_marks_analysis_failed_with_safe_error():
    engine, factory = _session_factory()
    _create_queued(factory)

    class FailedIngestion:
        def collect(self, _repository_url, progress):
            progress("Collecting commits", 45)
            raise GitHubRateLimited("raw API response should not be exposed")

        def close(self):
            pass

    run_analysis("analysis-1", session_factory=factory, ingestion_factory=FailedIngestion)
    with factory() as db:
        analysis = db.get(Analysis, "analysis-1")
        assert analysis.status == "failed"
        assert analysis.progress == 45
        assert analysis.error_code == "github_rate_limited"
        assert analysis.error_message == GitHubRateLimited.safe_message
        assert "raw API response" not in analysis.error_message
        assert analysis.completed_at is not None
        assert db.scalars(select(Evidence)).all() == []
    engine.dispose()


def test_unexpected_failure_does_not_expose_internal_details():
    engine, factory = _session_factory()
    _create_queued(factory)

    class FailedIngestion:
        def collect(self, _repository_url, _progress):
            raise RuntimeError("private filesystem path /secret/token")

        def close(self):
            pass

    run_analysis("analysis-1", session_factory=factory, ingestion_factory=FailedIngestion)
    with factory() as db:
        analysis = db.get(Analysis, "analysis-1")
        assert analysis.status == "failed"
        assert analysis.error_code == "ingestion_failed"
        assert "secret" not in analysis.error_message
    engine.dispose()


def test_restart_recovery_preserves_deterministic_results_and_marks_ai_failed():
    engine, factory = _session_factory()
    _create_queued(factory)
    deterministic = {"analysis_id": "analysis-1", "findings": [{"finding_id": "finding-1"}], "first_48_hours_plan": []}
    with factory() as db:
        analysis = db.get(Analysis, "analysis-1")
        analysis.status = "running"
        analysis.progress = 98
        analysis.current_stage = "Requesting local Ollama enrichment"
        db.add(AnalysisResult(analysis_id="analysis-1", result=deterministic))
        db.add(AIEnrichment(analysis_id="analysis-1", status="running", progress=25))
        db.commit()

    assert recover_interrupted_analyses(factory) == 1
    with factory() as db:
        analysis = db.get(Analysis, "analysis-1")
        assert analysis.status == "completed"
        assert analysis.current_stage == "Deterministic analysis complete; AI unavailable"
        assert db.get(AnalysisResult, "analysis-1").result == deterministic
        enrichment = db.get(AIEnrichment, "analysis-1")
        assert enrichment.status == "failed"
        assert enrichment.error_code == "worker_interrupted"
        assert "deterministic results remain available" in enrichment.error_message
    engine.dispose()


def test_restart_recovery_fails_jobs_without_saved_results_safely():
    engine, factory = _session_factory()
    _create_queued(factory)
    assert recover_interrupted_analyses(factory) == 1
    with factory() as db:
        analysis = db.get(Analysis, "analysis-1")
        assert analysis.status == "failed"
        assert analysis.error_code == "worker_interrupted"
        assert "server restart" in analysis.error_message
        assert "secret" not in analysis.error_message
    engine.dispose()
