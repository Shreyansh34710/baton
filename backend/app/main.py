"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes.health import router as health_router
from app.api.routes.projects import router as projects_router
from app.api.routes.analyses import router as analyses_router
from app.api.routes.ai_enrichment import router as ai_enrichment_router
from app.core.config import settings
from app.core.errors import http_exception_handler, unhandled_exception_handler
from app.db import session as db_session
from app.services.analysis_runner import recover_interrupted_analyses


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db_session.init_db()
    recover_interrupted_analyses(db_session.SessionLocal)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(health_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(analyses_router, prefix="/api/v1")
app.include_router(ai_enrichment_router, prefix="/api/v1")
