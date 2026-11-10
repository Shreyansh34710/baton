"""AI enrichment retrieval endpoints; deterministic results remain separate."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AIEnrichment, Analysis, AnalysisResult
from app.schemas.enrichment import (
    AIEnrichedPlanResponse, AIEnrichmentItemsResponse, AIEnrichmentResponse,
    AIEnrichmentStatusResponse, EnrichmentErrorDetails,
)

router = APIRouter(tags=["AI enrichment"])


def _load(analysis_id: str, db: Session):
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
    record = db.get(AIEnrichment, analysis_id)
    result = record.result if record and isinstance(record.result, dict) else {}
    error = None
    if record and (record.error_code or record.error_message):
        error = EnrichmentErrorDetails(
            code=record.error_code or "ai_enrichment_failed",
            message=record.error_message or "AI enrichment failed without additional details.",
        )
    return analysis, record, result, error


def _status(record: AIEnrichment) -> str:
    return record.status if record else "not_started"


@router.get("/analyses/{analysis_id}/ai-enrichment", response_model=AIEnrichmentResponse)
def get_ai_enrichment(
    analysis_id: str, db: Session = Depends(get_db)
) -> AIEnrichmentResponse:
    _analysis, record, result, error = _load(analysis_id, db)
    return AIEnrichmentResponse(
        analysis_id=analysis_id,
        status=_status(record),
        progress=record.progress if record else 0,
        items=result.get("items", []),
        generated_item_count=result.get("generated_item_count", 0),
        accepted_item_count=result.get("accepted_item_count", len(result.get("items", []))),
        rejected_item_count=result.get("rejected_item_count", 0),
        rejection_reason_counts=result.get("rejection_reason_counts", {}),
        rejection_diagnostics=result.get("rejection_diagnostics", []),
        error_details=error,
        started_at=record.started_at if record else None,
        completed_at=record.completed_at if record else None,
    )


@router.get("/analyses/{analysis_id}/ai-enrichment/status", response_model=AIEnrichmentStatusResponse)
def get_ai_enrichment_status(
    analysis_id: str, db: Session = Depends(get_db)
) -> AIEnrichmentStatusResponse:
    _analysis, record, result, error = _load(analysis_id, db)
    return AIEnrichmentStatusResponse(
        analysis_id=analysis_id,
        status=_status(record),
        progress=record.progress if record else 0,
        generated_item_count=result.get("generated_item_count", 0),
        accepted_item_count=result.get("accepted_item_count", len(result.get("items", []))),
        rejected_item_count=result.get("rejected_item_count", 0),
        rejection_reason_counts=result.get("rejection_reason_counts", {}),
        rejection_diagnostics=result.get("rejection_diagnostics", []),
        error_details=error,
        started_at=record.started_at if record else None,
        completed_at=record.completed_at if record else None,
    )


@router.get("/analyses/{analysis_id}/decisions", response_model=AIEnrichmentItemsResponse)
def get_reconstructed_decisions(
    analysis_id: str, db: Session = Depends(get_db)
) -> AIEnrichmentItemsResponse:
    _analysis, record, result, _error = _load(analysis_id, db)
    return AIEnrichmentItemsResponse(
        analysis_id=analysis_id,
        status=_status(record),
        items=[item for item in result.get("items", []) if item.get("category") == "technical_decision"],
    )


@router.get("/analyses/{analysis_id}/risks/explanations", response_model=AIEnrichmentItemsResponse)
def get_risk_explanations(
    analysis_id: str, db: Session = Depends(get_db)
) -> AIEnrichmentItemsResponse:
    _analysis, record, result, _error = _load(analysis_id, db)
    return AIEnrichmentItemsResponse(
        analysis_id=analysis_id,
        status=_status(record),
        items=[item for item in result.get("items", []) if item.get("category") == "risk"],
    )


@router.get("/analyses/{analysis_id}/plan/enriched", response_model=AIEnrichedPlanResponse)
def get_enriched_plan(
    analysis_id: str, db: Session = Depends(get_db)
) -> AIEnrichedPlanResponse:
    analysis, record, result, _error = _load(analysis_id, db)
    deterministic = db.get(AnalysisResult, analysis_id)
    if deterministic is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deterministic analysis results are not available yet.",
        )
    ai_items = [item for item in result.get("items", []) if item.get("category") == "plan"]
    return AIEnrichedPlanResponse(
        analysis_id=analysis.id,
        enrichment_status=_status(record),
        deterministic_plan=deterministic.result.get("first_48_hours_plan", []),
        ai_enrichments=ai_items,
    )
