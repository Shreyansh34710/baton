"""Environment-backed application configuration."""

from dataclasses import dataclass
import os
from typing import List


def _cors_origins(value: str) -> List[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    database_url: str
    cors_origins: List[str]
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_seconds: float


def get_settings() -> Settings:
    timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
    cors_origins = _cors_origins(
        os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        )
    )
    production_frontend_origin = "https://baton-cbbw.onrender.com"
    if production_frontend_origin not in cors_origins:
        cors_origins.append(production_frontend_origin)

    return Settings(
        app_name=os.getenv("APP_NAME", "BATON API"),
        app_env=os.getenv("APP_ENV", "development"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./baton.db"),
        cors_origins=cors_origins,
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
        ollama_timeout_seconds=timeout,
    )


settings = get_settings()
