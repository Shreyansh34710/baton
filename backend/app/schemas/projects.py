"""Project creation API schemas."""

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, field_validator


class ProjectCreateRequest(BaseModel):
    repository_url: str

    @field_validator("repository_url")
    @classmethod
    def validate_github_repository_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() != "https"
            or parsed.netloc.lower() != "github.com"
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(
                r"/[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/"
                r"[A-Za-z0-9_.-]+/?",
                parsed.path,
            )
        ):
            raise ValueError("Use a GitHub repository URL like https://github.com/owner/repository.")
        repository_name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if repository_name in (".", ".."):
            raise ValueError("The repository name is invalid.")
        return "https://github.com" + parsed.path.rstrip("/")


class ProjectAnalysisCreateResponse(BaseModel):
    project_id: str
    analysis_id: str
    status: Literal["queued", "running", "completed", "failed"]
