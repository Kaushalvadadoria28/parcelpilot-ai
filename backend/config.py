"""Application configuration, loaded from environment variables / .env.

This module intentionally stays minimal at this stage of the project. It
declares only the settings the current scaffold needs (paths and runtime
metadata). Later milestones extend `Settings` alongside the code that
consumes each new field (e.g. document-manifest paths land with the
ingestion milestone, not before) rather than pre-declaring configuration
surface for features that don't exist yet.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    # Directory containing the locally-supplied assessment data pack.
    # See data/README.md for the expected layout.
    data_dir: Path = Path("data")

    # Directory for generated/build artifacts (SQLite DB, document index
    # cache). Rebuilt by the ingestion pipeline; safe to delete at any time.
    var_dir: Path = Path("var")

    anthropic_api_key: str | None = None


settings = Settings()
