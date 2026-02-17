from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TELNYX_FAX_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Telnyx Fax OSS Example"
    environment: str = "development"
    base_url: str = "http://localhost:8000"
    app_secret_key: str = "dev-insecure-change-me"

    database_url: str = Field(
        default="sqlite:///./data/fax_demo.db",
        validation_alias=AliasChoices("TELNYX_FAX_DATABASE_URL", "DATABASE_URL"),
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800
    auto_create_schema: bool = True

    uploads_dir: str = "data/uploads"
    storage_backend: str = "local"  # local | s3
    storage_presign_ttl_seconds: int = 900
    max_upload_size_mb: int = 15
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_prefix: str = "uploads"
    s3_public_base_url: str | None = None

    supported_country_codes: str = "US"
    max_pages_per_job: int = 25

    rate_limit_ip_per_hour: int = 200

    retention_hours: int = 24
    logs_retention_days: int = 30

    telnyx_api_key: str | None = None
    telnyx_connection_id: str | None = None
    telnyx_from_number: str | None = None
    telnyx_webhook_public_key: str | None = None
    webhook_timestamp_tolerance_seconds: int = 300

    resend_api_key: str | None = None
    resend_from_email: str | None = None
    resend_api_base_url: str = "https://api.resend.com"

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "no-reply@example.com"

    internal_admin_token: str | None = None
    mock_providers: bool = True

    @property
    def uploads_path(self) -> Path:
        path = Path(self.uploads_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def storage_backend_name(self) -> str:
        return self.storage_backend.strip().lower()

    @property
    def max_upload_size_bytes(self) -> int:
        return max(self.max_upload_size_mb, 1) * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @property
    def is_live_telnyx(self) -> bool:
        return bool(self.telnyx_api_key and self.telnyx_connection_id and self.telnyx_from_number)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
