"""
Centralized configuration via Pydantic BaseSettings.
Reads from .env file or environment variables — no hardcoded secrets.
"""

from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Messaging ---
    ingestion_topic: str = "logs.raw"

    # --- PostgreSQL ---
    database_url: str = "postgresql+asyncpg://soc_user:soc_pass_dev@localhost:5432/soc_db"

    @field_validator("database_url", mode="after")
    @classmethod
    def fix_postgres_scheme(cls, v: str) -> str:
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgresql://") and not v.startswith("postgresql+asyncpg://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- ML ---
    anomaly_threshold: float = 0.7
    model_dir: str = "app/ml/artifacts"

    # --- Alerting ---
    alert_cooldown_seconds: int = 60
    webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""

    # --- App ---
    log_level: str = "INFO"

    @property
    def model_path(self) -> Path:
        return Path(self.model_dir)


settings = Settings()
