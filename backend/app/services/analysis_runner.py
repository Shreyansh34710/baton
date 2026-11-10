"""Background worker coordinating GitHub ingestion and analysis lifecycle."""

from datetime import datetime, timezone
from typing import Callable, Optional
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import SessionLocal
from app.models import AIEnrichment, Analysis, AnalysisResult, Evidence, Project
from app.services.github_client import GitHubIngestionError
from app.services.deterministic_analyzer import DeterministicAnalyzer
from app.services.github_ingestion import GitHubIngestionService
from app.services.ollama_client import OllamaError
from app.services.ollama_enrichment import OllamaEnrichmentService, REJECTION_REASONS


def run_analysis(
    analysis_id: str,
    session_factory: Optional[sessionmaker] = None,
    ingestion_factory: Callable[[], GitHubIngestionService] = GitHubIngestionService,
    analyzer_factory: Callable[[], DeterministicAnalyzer] = DeterministicAnalyzer,
    enrichment_factory: Callable[[], OllamaEnrichmentService] = OllamaEnrichmentService,
) -> None:
    """Ingest repository evidence, persist deterministic analysis, then complete."""
    factory = session_factory or SessionLocal
    db: Session = factory()
    service = None
    enrichment_service = None
    failure_code = "ingestion_failed"
    failure_message = "Repository ingestion failed. Please retry the analysis."
    try:
        analysis = db.get(Analysis, analysis_id)
        if analysis is None or analysis.status != "queued":
            return
        project = db.get(Project, analysis.project_id)
        if project is None:
            raise RuntimeError("project_missing")
        analysis.status = "running"
        analysis.started_at = datetime.now(timezone.utc)
        analysis.current_stage = "Fetching repository information"
        analysis.progress = 1
        db.commit()

        service = ingestion_factory()

        def update_progress(stage: str, progress: int) -> None:
            current = db.get(Analysis, analysis_id)
            if current is None or current.status != "running":
                raise RuntimeError("analysis_unavailable")
            current.current_stage = stage[:64]
            current.progress = max(current.progress, min(99, max(1, progress)))
            db.commit()

        evidence_drafts = service.collect(project.repository_url, update_progress)
        current = db.get(Analysis, analysis_id)
        if current is None or current.status != "running":
            raise RuntimeError("analysis_unavailable")
        current.current_stage = "Saving repository evidence"
        current.progress = max(current.progress, 95)
        db.commit()

        for draft in evidence_drafts:
            db.add(Evidence(
                id=str(uuid4()), project_id=project.id, analysis_id=analysis_id,
                evidence_type=draft.evidence_type, source_identifier=draft.source_identifier,
                source_url=draft.source_url, content=draft.content,
                retrieved_at=draft.retrieved_at, repository_commit_sha=draft.repository_commit_sha,
            ))
        db.commit()

        current = db.get(Analysis, analysis_id)
        if current is None:
            raise RuntimeError("analysis_unavailable")
        current.current_stage = "Analyzing repository evidence"
        current.progress = 96
        db.commit()

        failure_code = "analysis_failed"
        failure_message = "Deterministic project analysis failed. Please retry the analysis."
        analysis_result = analyzer_factory().analyze(analysis_id, db)
        current = db.get(Analysis, analysis_id)
        if current is None or current.status != "running":
            raise RuntimeError("analysis_unavailable")
        current.current_stage = "Saving analysis findings"
        current.progress = 97
        saved_result = db.get(AnalysisResult, analysis_id)
        if saved_result is None:
            saved_result = AnalysisResult(analysis_id=analysis_id, result=analysis_result)
            db.add(saved_result)
        else:
            saved_result.result = analysis_result
        db.commit()

        current = db.get(Analysis, analysis_id)
        if current is None or current.status != "running":
            raise RuntimeError("analysis_unavailable")
        current.current_stage = "Enriching with local Ollama"
        current.progress = 98
        enrichment_row = db.get(AIEnrichment, analysis_id)
        if enrichment_row is None:
            enrichment_row = AIEnrichment(analysis_id=analysis_id, status="running")
            db.add(enrichment_row)
        else:
            enrichment_row.status = "running"
            enrichment_row.error_code = None
            enrichment_row.error_message = None
            enrichment_row.result = None
        db.commit()

        def update_enrichment_progress(stage: str, progress: int) -> None:
            current_analysis = db.get(Analysis, analysis_id)
            if current_analysis is None or current_analysis.status != "running":
                raise RuntimeError("analysis_unavailable")
            current_analysis.current_stage = stage[:64]
            current_analysis.progress = max(current_analysis.progress, 98 if progress < 90 else 99)
            current_enrichment = db.get(AIEnrichment, analysis_id)
            current_enrichment.progress = max(current_enrichment.progress, min(99, max(0, progress)))
            db.commit()

        try:
            enrichment_service = enrichment_factory()
            enrichment_result = enrichment_service.enrich(
                analysis_id, analysis_result, db, update_enrichment_progress
            )
            enrichment_row = db.get(AIEnrichment, analysis_id)
            current_analysis = db.get(Analysis, analysis_id)
            current_analysis.current_stage = "Saving AI enrichment"
            current_analysis.progress = 99
            enrichment_row.progress = 100
            enrichment_row.status = enrichment_result["status"]
            enrichment_row.result = {
                "items": enrichment_result["items"],
                "generated_item_count": enrichment_result.get("generated_item_count", 0),
                "accepted_item_count": enrichment_result.get("accepted_item_count", len(enrichment_result["items"])),
                "rejected_item_count": enrichment_result["rejected_item_count"],
                "rejection_reason_counts": enrichment_result.get("rejection_reason_counts", {}),
                "rejection_diagnostics": enrichment_result.get("rejection_diagnostics", []),
            }
            enrichment_row.error_code = (
                "ollama_output_partially_rejected" if enrichment_result["rejected_item_count"]
                else "ollama_output_needs_review" if enrichment_result["status"] == "partial"
                else None
            )
            enrichment_row.error_message = enrichment_result["error_message"]
        except OllamaError as exc:
            db.rollback()
            enrichment_row = db.get(AIEnrichment, analysis_id)
            enrichment_row.status = "failed"
            enrichment_row.error_code = exc.code
            enrichment_row.error_message = exc.safe_message
            diagnostic_category = exc.diagnostic_category if exc.diagnostic_category in REJECTION_REASONS else None
            enrichment_row.result = {
                "items": [], "generated_item_count": 0, "accepted_item_count": 0,
                "rejected_item_count": 0,
                "rejection_reason_counts": {diagnostic_category: 1} if diagnostic_category else {},
                "rejection_diagnostics": [{"stage": "response", "reason": diagnostic_category}]
                if diagnostic_category else [],
            }
        except Exception:
            db.rollback()
            enrichment_row = db.get(AIEnrichment, analysis_id)
            enrichment_row.status = "failed"
            enrichment_row.error_code = "ollama_generation_failed"
            enrichment_row.error_message = OllamaError.safe_message
            enrichment_row.result = {"items": [], "generated_item_count": 0, "accepted_item_count": 0,
                                     "rejected_item_count": 0, "rejection_reason_counts": {},
                                     "rejection_diagnostics": []}
        finally:
            if enrichment_service is not None:
                try:
                    enrichment_service.close()
                except Exception:
                    pass
                enrichment_service = None

        enrichment_row.completed_at = datetime.now(timezone.utc)
        final_enrichment_status = enrichment_row.status
        db.commit()

        current = db.get(Analysis, analysis_id)
        if current is None:
            raise RuntimeError("analysis_unavailable")
        current.status = "completed"
        current.progress = 100
        current.current_stage = {
            "completed": "Analysis complete",
            "partial": "Deterministic analysis complete; AI needs review",
            "failed": "Deterministic analysis complete; AI unavailable",
        }.get(final_enrichment_status, "Analysis complete")
        current.completed_at = datetime.now(timezone.utc)
        current.error_code = None
        current.error_message = None
        db.commit()
    except GitHubIngestionError as exc:
        db.rollback()
        _mark_failed(db, analysis_id, exc.code, exc.safe_message)
    except Exception:
        db.rollback()
        _mark_failed(db, analysis_id, failure_code, failure_message)
    finally:
        if service is not None:
            try:
                service.close()
            except Exception:
                pass
        if enrichment_service is not None:
            try:
                enrichment_service.close()
            except Exception:
                pass
        db.close()


def _mark_failed(db: Session, analysis_id: str, code: str, message: str) -> None:
    try:
        analysis = db.get(Analysis, analysis_id)
        if analysis is None:
            return
        analysis.status = "failed"
        analysis.error_code = code[:64]
        analysis.error_message = message[:500]
        analysis.current_stage = "Analysis failed"
        analysis.completed_at = datetime.now(timezone.utc)
        db.commit()
    except SQLAlchemyError:
        db.rollback()


def recover_interrupted_analyses(session_factory: Optional[sessionmaker] = None) -> int:
    """Close stale in-process jobs after restart, preserving saved deterministic results."""
    factory = session_factory or SessionLocal
    db: Session = factory()
    now = datetime.now(timezone.utc)
    recovered = 0
    try:
        interrupted = db.scalars(
            select(Analysis).where(Analysis.status.in_(("queued", "running")))
        ).all()
        for analysis in interrupted:
            saved_result = db.get(AnalysisResult, analysis.id)
            enrichment = db.get(AIEnrichment, analysis.id)
            if saved_result is None:
                analysis.status = "failed"
                analysis.error_code = "worker_interrupted"
                analysis.error_message = "Analysis was interrupted by a server restart before results were saved. Submit the repository again."
                analysis.current_stage = "Analysis interrupted"
                analysis.completed_at = now
                recovered += 1
                continue

            if enrichment is None:
                enrichment = AIEnrichment(
                    analysis_id=analysis.id, status="failed", progress=100,
                    result={"items": [], "rejected_item_count": 0},
                    error_code="worker_interrupted",
                    error_message="AI enrichment was interrupted; deterministic results remain available.",
                    started_at=analysis.started_at or now, completed_at=now,
                )
                db.add(enrichment)
            elif enrichment.status == "running":
                enrichment.status = "failed"
                enrichment.progress = 100
                enrichment.result = {"items": [], "rejected_item_count": 0}
                enrichment.error_code = "worker_interrupted"
                enrichment.error_message = "AI enrichment was interrupted; deterministic results remain available."
                enrichment.completed_at = now
            elif enrichment.completed_at is None:
                enrichment.completed_at = now

            analysis.status = "completed"
            analysis.progress = 100
            analysis.current_stage = {
                "completed": "Analysis complete",
                "partial": "Deterministic analysis complete; AI needs review",
                "failed": "Deterministic analysis complete; AI unavailable",
            }.get(enrichment.status, "Deterministic analysis complete; AI unavailable")
            analysis.error_code = None
            analysis.error_message = None
            analysis.completed_at = analysis.completed_at or now
            recovered += 1
        db.commit()
        return recovered
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
