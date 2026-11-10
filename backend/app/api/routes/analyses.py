"""Analysis lifecycle endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AIEnrichment, Analysis, AnalysisResult
from app.schemas.analyses import AnalysisErrorDetails, AnalysisStatusResponse
from app.schemas.results import (
    AnalysisResultsResponse, ContributorsResponse, EvidenceDetail, FindingCategory,
    FindingsResponse, PlanResponse,
)
from app.models import Evidence

router = APIRouter(tags=["analyses"])


@router.get("/analyses/{analysis_id}", response_model=AnalysisStatusResponse)
def get_analysis_status(
    analysis_id: str, db: Session = Depends(get_db)
) -> AnalysisStatusResponse:
    try:
        analysis = db.get(Analysis, analysis_id)
        enrichment = db.get(AIEnrichment, analysis_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve the analysis status.",
        ) from exc
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
    error_details = None
    if analysis.error_code or analysis.error_message:
        error_details = AnalysisErrorDetails(
            code=analysis.error_code or "analysis_failed",
            message=analysis.error_message or "Analysis failed without additional details.",
        )
    return AnalysisStatusResponse(
        analysis_id=analysis.id,
        project_id=analysis.project_id,
        status=analysis.status,
        progress=analysis.progress,
        current_stage=analysis.current_stage,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
        error_details=error_details,
        ai_enrichment_status=enrichment.status if enrichment else "not_started",
        ai_enrichment_progress=enrichment.progress if enrichment else 0,
        ai_enrichment_error=(
            AnalysisErrorDetails(
                code=enrichment.error_code or "ai_enrichment_failed",
                message=enrichment.error_message or "AI enrichment failed without additional details.",
            )
            if enrichment and enrichment.error_code or enrichment and enrichment.error_message
            else None
        ),
    )


def _analysis_result(analysis_id: str, db: Session) -> dict:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
    saved = db.get(AnalysisResult, analysis_id)
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Analysis results are not available yet.",
        )
    return saved.result


@router.get("/analyses/{analysis_id}/results", response_model=AnalysisResultsResponse)
def get_analysis_results(
    analysis_id: str, db: Session = Depends(get_db)
) -> AnalysisResultsResponse:
    try:
        return _analysis_result(analysis_id, db)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve analysis results.",
        ) from exc


@router.get(
    "/analyses/{analysis_id}/evidence/{evidence_id}",
    response_model=EvidenceDetail,
)
def get_analysis_evidence(
    analysis_id: str, evidence_id: str, db: Session = Depends(get_db)
) -> EvidenceDetail:
    try:
        analysis = db.get(Analysis, analysis_id)
        if analysis is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found.")
        evidence = db.get(Evidence, evidence_id)
        if evidence is None or evidence.analysis_id != analysis_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found.")
        saved = db.get(AnalysisResult, analysis_id)
        related_ids = []
        if saved and isinstance(saved.result, dict):
            related_ids = [
                item["finding_id"] for item in saved.result.get("findings", [])
                if evidence_id in item.get("evidence_ids", [])
            ]
        return EvidenceDetail(
            evidence_id=evidence.id,
            evidence_type=evidence.evidence_type,
            source_identifier=evidence.source_identifier,
            source_url=evidence.source_url,
            retrieved_at=evidence.retrieved_at,
            repository_commit_sha=evidence.repository_commit_sha,
            content=evidence.content,
            related_finding_ids=related_ids,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve evidence details.",
        ) from exc


@router.get("/analyses/{analysis_id}/findings", response_model=FindingsResponse)
def get_analysis_findings(
    analysis_id: str,
    category: FindingCategory = Query(...),
    db: Session = Depends(get_db),
) -> FindingsResponse:
    try:
        result = _analysis_result(analysis_id, db)
        return FindingsResponse(
            analysis_id=analysis_id,
            findings=[finding for finding in result["findings"] if finding["category"] == category],
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve analysis findings.",
        ) from exc


@router.get("/analyses/{analysis_id}/risks", response_model=FindingsResponse)
def get_analysis_risks(
    analysis_id: str, db: Session = Depends(get_db)
) -> FindingsResponse:
    try:
        result = _analysis_result(analysis_id, db)
        return FindingsResponse(
            analysis_id=analysis_id,
            findings=[finding for finding in result["findings"] if finding["category"] == "risk"],
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve analysis risks.",
        ) from exc


@router.get("/analyses/{analysis_id}/contributors", response_model=ContributorsResponse)
def get_analysis_contributors(
    analysis_id: str, db: Session = Depends(get_db)
) -> ContributorsResponse:
    try:
        result = _analysis_result(analysis_id, db)
        return ContributorsResponse(
            analysis_id=analysis_id,
            contributors=[finding for finding in result["findings"] if finding["category"] == "contributor"],
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve contributor activity.",
        ) from exc


@router.get("/analyses/{analysis_id}/plan", response_model=PlanResponse)
def get_analysis_plan(
    analysis_id: str, db: Session = Depends(get_db)
) -> PlanResponse:
    try:
        result = _analysis_result(analysis_id, db)
        return PlanResponse(
            analysis_id=analysis_id,
            first_48_hours_plan=result["first_48_hours_plan"],
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve the onboarding plan.",
        ) from exc
