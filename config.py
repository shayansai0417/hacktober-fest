"""Environment-backed configuration for PaperGrade AI."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from functools import cached_property

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    app_secret_key: str = Field(default="", alias="APP_SECRET_KEY")
    demo_mode: bool = Field(default=True, alias="DEMO_MODE")
    gemma_api_key: str = Field(default="", alias="GEMMA_API_KEY")
    gemma_model: str = Field(default="gemma-4-26b-a4b-it", alias="GEMMA_MODEL")
    database_url: str = Field(default=f"sqlite:///{(ROOT_DIR / 'papergrade.db').as_posix()}", alias="DATABASE_URL")
    upload_dir: Path = Field(default=ROOT_DIR / "storage" / "uploads", alias="UPLOAD_DIR")
    max_upload_mb: int = Field(default=20, alias="MAX_UPLOAD_MB", ge=1, le=100)
    gemma_timeout_seconds: int = Field(default=300, alias="GEMMA_TIMEOUT_SECONDS", ge=10, le=300)
    gemma_image_batch_size: int = Field(default=12, alias="GEMMA_IMAGE_BATCH_SIZE", ge=1, le=12)
    teacher_name: str = Field(default="Maya Patel", alias="TEACHER_NAME")
    institution: str = Field(default="Northstar Learning Centre", alias="INSTITUTION")
    teacher_email: str = Field(default="maya@northstar.edu", alias="TEACHER_EMAIL")
    demo_login_enabled: bool = Field(default=True, alias="DEMO_LOGIN_ENABLED")
    demo_login_email: str = Field(default="demo@papergrade.ai", alias="DEMO_LOGIN_EMAIL")
    demo_login_password: str = Field(default="DemoPaperGrade2026!", alias="DEMO_LOGIN_PASSWORD")
    require_email_verification: bool = Field(default=False, alias="REQUIRE_EMAIL_VERIFICATION")
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT", ge=1, le=65535)
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from_email: str = Field(default="", alias="SMTP_FROM_EMAIL")
    app_url: str = Field(default="", alias="PUBLIC_APP_URL")

    @property
    def live_ready(self) -> bool:
        return bool(self.gemma_api_key.strip())

    @property
    def demo_login_available(self) -> bool:
        # A public demo account must never be implicitly enabled on a production deployment.
        return self.demo_login_enabled and self.app_env.casefold() not in {"production", "prod"}

    @property
    def is_production(self) -> bool:
        return self.app_env.casefold() in {"production", "prod"}

    @cached_property
    def auth_secret(self) -> str:
        # Production must supply APP_SECRET_KEY. The process-random local fallback
        # keeps development convenient while making reset tokens expire on restart.
        return self.app_secret_key or secrets.token_urlsafe(48)

    def validate_production_configuration(self) -> None:
        if not self.is_production:
            return
        if len(self.app_secret_key.encode("utf-8")) < 32:
            raise RuntimeError("Production requires APP_SECRET_KEY with at least 32 bytes of entropy.")
        if not self.database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
            raise RuntimeError("Production deployments must use PostgreSQL through DATABASE_URL.")
        if not self.smtp_ready:
            raise RuntimeError("Production requires SMTP_HOST and SMTP_FROM_EMAIL for account verification and recovery.")
        if not self.gemma_api_key.strip():
            raise RuntimeError("Production requires GEMMA_API_KEY to enable live grading.")

    @property
    def smtp_ready(self) -> bool:
        return bool(self.smtp_host.strip() and self.smtp_from_email.strip())

    @property
    def effective_app_url(self) -> str:
        return self.app_url.strip() or os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8501").strip()


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)

