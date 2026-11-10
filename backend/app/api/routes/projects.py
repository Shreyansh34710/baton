"""Project lifecycle endpoints."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.projects import ProjectAnalysisCreateResponse, ProjectCreateRequest
from app.services.projects import create_project_with_analysis
from app.services.analysis_runner import run_analysis

router = APIRouter(tags=["projects"])


@router.post(
    "/projects",
    response_model=ProjectAnalysisCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    request: ProjectCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ProjectAnalysisCreateResponse:
    try:
        project, analysis = create_project_with_analysis(db, request.repository_url)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create the project and analysis record.",
        ) from exc
    background_tasks.add_task(run_analysis, analysis.id)
    return ProjectAnalysisCreateResponse(
        project_id=project.id, analysis_id=analysis.id, status=analysis.status
    )
