from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASSESSMENT_",
        env_file=".env",
        env_file_encoding="utf-8-sig",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: SecretStr = Field(repr=False)
    migration_database_url: SecretStr | None = Field(default=None, repr=False)
    worker_database_url: SecretStr | None = Field(default=None, repr=False)
    outbox_lease_seconds: int = Field(default=60, ge=5, le=600)
    outbox_retry_base_seconds: int = Field(default=2, ge=1, le=60)
    session_lifetime_seconds: int = Field(default=3600, ge=300, le=86400)
    login_window_seconds: int = Field(default=300, ge=60, le=3600)
    login_account_limit: int = Field(default=10, ge=3, le=100)
    login_ip_limit: int = Field(default=500, ge=30, le=5000)

    @property
    def migration_url(self) -> SecretStr:
        return self.migration_database_url or self.database_url

    database_connect_timeout: int = Field(default=3, ge=1, le=30)
    database_pool_timeout: int = Field(default=3, ge=1, le=30)
    database_statement_timeout_ms: int = Field(default=5000, ge=100, le=30000)

    @field_validator("database_url", "migration_database_url", "worker_database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            url = make_url(value.get_secret_value())
        except (ArgumentError, ValueError) as exc:
            raise ValueError("A valid PostgreSQL connection URL is required") from exc
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError("Use postgresql+psycopg and specify a database")
        return value
