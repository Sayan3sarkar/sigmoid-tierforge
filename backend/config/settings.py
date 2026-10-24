from typing import Annotated

from fastapi import Depends
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class BaseSettingsConfig(BaseSettings):
    app_name: str = "tierforge"
    environment: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True
    )

    def __init_subclass__(cls, env_prefix: str = "", **kwargs):
        super().__init_subclass__(**kwargs)
        if env_prefix:
            parent_config = getattr(cls, "model_config", {})
            cls.model_config = SettingsConfigDict(
                **parent_config, env_prefix=env_prefix
            )


class DBConfig(BaseSettingsConfig, env_prefix="database_"):
    url: str  # user:password@host:port/database
    echo_sql: bool = False

    @property
    def async_url(self) -> str:
        return f"postgresql+asyncpg://{self.url}"


class AWSConfig(BaseSettingsConfig, env_prefix="aws_"):
    # Unset (None) in AWS: botocore then uses the real endpoint and the IAM role.
    endpoint_url: str | None = None
    region: str = "us-east-1"
    access_key_id: str | None = None
    secret_access_key: str | None = None


class SQSConfig(BaseSettingsConfig, env_prefix="sqs_"):
    enrichment_queue_url: str  # existing queue; provisioned outside this code
    wait_time_seconds: int = 20
    max_messages: int = 10
    send_concurrency: int = 10  # SendMessageBatch calls in flight at once


class EnrichmentConfig(BaseSettingsConfig, env_prefix="enrichment_"):
    base_url: str = "http://localhost:8000"
    # Whole call, from connecting to the last byte of the response.
    timeout_seconds: float = Field(default=10.0, gt=0)
    # The API allows 5 calls/s across all callers; stay below it.
    rate_per_second: float = Field(default=4.5, gt=0)
    # Calls in flight at once in one worker; the rate limit still caps calls/s.
    concurrency: int = Field(default=8, ge=1)


class HealthConfig(BaseSettingsConfig, env_prefix="health_"):
    postgres_timeout_seconds: float = 2.0


class UploadConfig(BaseSettingsConfig, env_prefix="upload_"):
    max_size_bytes: int = 10 * 1024 * 1024


class Config(BaseSettingsConfig):
    log_level: str = "INFO"
    # Origins a browser frontend may call the API from (CORS). In the env, a
    # comma-separated list, e.g.
    # ALLOWED_ORIGINS=http://localhost:5173,https://app.example.com
    # "*" allows any origin.
    allowed_origins: Annotated[list[str], NoDecode] = ["*"]
    db: DBConfig = Field(default_factory=DBConfig)
    aws: AWSConfig = Field(default_factory=AWSConfig)
    sqs: SQSConfig = Field(default_factory=SQSConfig)
    enrichment: EnrichmentConfig = Field(default_factory=EnrichmentConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    upload: UploadConfig = Field(default_factory=UploadConfig)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        """Read a comma-separated env value as a list of origins."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


cfg = Config()


def get_config() -> Config:
    return cfg


ConfigDep = Annotated[Config, Depends(get_config)]
