"""Analysis lifecycle API schemas."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, conint


class AnalysisErrorDetails(BaseModel):
    code: str
    message: str


class AnalysisStatusResponse(BaseModel):
    analysis_id: str
    project_id: str
    status: Literal["queued", "running", "completed", "failed"]
    progress: conint(ge=0, le=100)
    current_stage: str
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_details: Optional[AnalysisErrorDetails] = None
    ai_enrichment_status: Literal["not_started", "running", "completed", "partial", "failed"] = "not_started"
    ai_enrichment_progress: conint(ge=0, le=100) = 0
    ai_enrichment_error: Optional[AnalysisErrorDetails] = None
