from typing import Annotated

from fastapi import Depends
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class EnrichmentConfig(BaseSettingsConfig, env_prefix="enrichment_"):
    base_url: str = "http://localhost:8000"


class HealthConfig(BaseSettingsConfig, env_prefix="health_"):
    postgres_timeout_seconds: float = 2.0


class UploadConfig(BaseSettingsConfig, env_prefix="upload_"):
    max_size_bytes: int = 10 * 1024 * 1024


class Config(BaseSettingsConfig):
    log_level: str = "INFO"
    db: DBConfig = Field(default_factory=DBConfig)
    aws: AWSConfig = Field(default_factory=AWSConfig)
    sqs: SQSConfig = Field(default_factory=SQSConfig)
    enrichment: EnrichmentConfig = Field(default_factory=EnrichmentConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    upload: UploadConfig = Field(default_factory=UploadConfig)


cfg = Config()


def get_config() -> Config:
    return cfg


ConfigDep = Annotated[Config, Depends(get_config)]
