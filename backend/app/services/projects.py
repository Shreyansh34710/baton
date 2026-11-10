"""Project and initial analysis creation operations."""

from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Analysis, Project


def create_project_with_analysis(db: Session, repository_url: str) -> tuple[Project, Analysis]:
    project = Project(id=str(uuid4()), repository_url=repository_url)
    analysis = Analysis(
        id=str(uuid4()), project_id=project.id, status="queued", progress=0,
        current_stage="queued",
    )
    try:
        db.add(project)
        db.add(analysis)
        db.commit()
        db.refresh(project)
        db.refresh(analysis)
    except SQLAlchemyError:
        db.rollback()
        raise
    return project, analysis
