"""Ollama output validation and public AI enrichment response schemas."""

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


EnrichmentCategory = Literal[
    "project_understanding", "technical_decision", "work_status",
    "risk", "knowledge_gap", "plan",
]
ClaimType = Literal["fact", "inference", "unknown"]
EvidenceStatus = Literal["source_verified", "partially_verified", "insufficient"]
EnrichmentStatus = Literal["not_started", "running", "completed", "partial", "failed"]
RejectionReason = Literal[
    "invalid_json", "missing_required_field", "unknown_evidence_alias",
    "unknown_finding_alias", "unknown_task_alias", "invalid_category",
    "invalid_claim_type", "invalid_output_structure", "unsupported_reference",
    "other_schema_validation_failure", "duplicate_item", "truncated_response",
]


class AIRejectionDiagnostic(BaseModel):
    stage: Literal["response", "schema", "reference"]
    reason: RejectionReason
    item_index: Optional[int] = Field(default=None, ge=0)


class OllamaEnrichmentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: EnrichmentCategory
    title: str = Field(min_length=1, max_length=180)
    explanation: str = Field(min_length=1, max_length=2400)
    claim_type: ClaimType
    confidence: float = Field(ge=0, le=1)
    evidence_ids: List[str] = Field(min_length=1, max_length=20)
    finding_ids: List[str] = Field(min_length=1, max_length=12)
    plan_task_ids: List[str] = Field(max_length=8)
    recommended_action: Optional[str] = Field(default=None, max_length=600)


class OllamaEnrichmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: List[OllamaEnrichmentItem] = Field(default_factory=list, max_length=30)


class EnrichmentErrorDetails(BaseModel):
    code: str
    message: str


class AIEnrichmentItem(BaseModel):
    enrichment_id: str
    category: EnrichmentCategory
    title: str
    explanation: str
    claim_type: ClaimType
    evidence_status: EvidenceStatus
    confidence: float = Field(ge=0, le=1)
    evidence_ids: List[str]
    related_finding_ids: List[str]
    plan_task_ids: List[str]
    recommended_action: Optional[str] = None
    human_review_status: Literal["needs_review"] = "needs_review"


class AIEnrichmentResponse(BaseModel):
    analysis_id: str
    status: EnrichmentStatus
    progress: int = Field(ge=0, le=100)
    items: List[AIEnrichmentItem] = Field(default_factory=list)
    generated_item_count: int = 0
    accepted_item_count: int = 0
    rejected_item_count: int = 0
    rejection_reason_counts: Dict[str, int] = Field(default_factory=dict)
    rejection_diagnostics: List[AIRejectionDiagnostic] = Field(default_factory=list)
    error_details: Optional[EnrichmentErrorDetails] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AIEnrichmentStatusResponse(BaseModel):
    analysis_id: str
    status: EnrichmentStatus
    progress: int = Field(ge=0, le=100)
    generated_item_count: int = 0
    accepted_item_count: int = 0
    rejected_item_count: int = 0
    rejection_reason_counts: Dict[str, int] = Field(default_factory=dict)
    rejection_diagnostics: List[AIRejectionDiagnostic] = Field(default_factory=list)
    error_details: Optional[EnrichmentErrorDetails] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AIEnrichmentItemsResponse(BaseModel):
    analysis_id: str
    status: EnrichmentStatus
    items: List[AIEnrichmentItem]


class AIEnrichedPlanResponse(BaseModel):
    analysis_id: str
    enrichment_status: EnrichmentStatus
    deterministic_plan: List[dict]
    ai_enrichments: List[AIEnrichmentItem]
