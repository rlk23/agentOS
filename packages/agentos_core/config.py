from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn = "postgresql+asyncpg://agentos:agentos@127.0.0.1:55432/agentos"
    redis_url: RedisDsn = "redis://127.0.0.1:56379/0"
    redis_queue_key: str = Field(default="agentos:tasks", min_length=1)
    dispatch_interval_seconds: float = Field(default=1, gt=0)
    redispatch_seconds: int = Field(default=30, ge=1)
    dispatch_batch_size: int = Field(default=50, ge=1, le=1000)
