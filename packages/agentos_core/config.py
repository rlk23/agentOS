from pydantic import Field, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn = "postgresql+asyncpg://agentos:agentos@127.0.0.1:55432/agentos"
    redis_url: RedisDsn = "redis://127.0.0.1:56379/0"
    redis_queue_key: str = Field(default="agentos:tasks", min_length=1)
    dispatch_interval_seconds: float = Field(default=1, gt=0)
    redispatch_seconds: int = Field(default=30, ge=1)
    dispatch_batch_size: int = Field(default=50, ge=1, le=1000)
    openai_api_key: SecretStr | None = None
    openai_model: str = Field(default="gpt-4.1-mini", min_length=1)
    sandbox_image: str = Field(default="agentos-sandbox:0.1", min_length=1)
    agent_max_turns: int = Field(default=12, ge=1, le=30)
    agent_max_tool_calls: int = Field(default=24, ge=1, le=60)
    agent_max_output_tokens: int = Field(default=4096, ge=256, le=8192)
    agent_command_timeout_seconds: int = Field(default=30, ge=1, le=60)
    agent_max_runtime_seconds: int = Field(default=600, ge=1, le=900)
