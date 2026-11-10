"""Structured response schemas for deterministic analysis results."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


FindingCategory = Literal[
    "overview", "completed", "ongoing", "unfinished", "technical_decision",
    "contributor", "risk", "knowledge_gap",
]
ClaimType = Literal["fact", "inference", "unknown"]
EvidenceStatus = Literal["source_verified", "partially_verified", "insufficient", "not_applicable"]
Priority = Literal["high", "medium", "low"]
Timeframe = Literal["first_2_hours", "first_8_hours", "first_24_hours", "first_48_hours"]


class EvidenceReference(BaseModel):
    evidence_id: str
    evidence_type: str
    source_identifier: str
    source_url: str
    retrieved_at: datetime
    repository_commit_sha: Optional[str] = None


class EvidenceDetail(EvidenceReference):
    content: str
    related_finding_ids: List[str] = Field(default_factory=list)


class Finding(BaseModel):
    finding_id: str
    category: FindingCategory
    title: str
    description: str
    claim_type: ClaimType
    evidence_status: EvidenceStatus
    confidence: float = Field(ge=0, le=1)
    evidence_ids: List[str] = Field(default_factory=list)
    recommended_next_action: Optional[str] = None


class OnboardingTask(BaseModel):
    task_id: str
    timeframe: Timeframe
    title: str
    reason: str
    priority: Priority
    finding_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)


class AnalysisResultsResponse(BaseModel):
    analysis_id: str
    project_id: str
    findings: List[Finding]
    evidence_references: List[EvidenceReference]
    first_48_hours_plan: List[OnboardingTask]


class FindingsResponse(BaseModel):
    analysis_id: str
    findings: List[Finding]


class ContributorsResponse(BaseModel):
    analysis_id: str
    contributors: List[Finding]


class PlanResponse(BaseModel):
    analysis_id: str
    first_48_hours_plan: List[OnboardingTask]
