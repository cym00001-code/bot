from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8008
    public_base_url: str = "http://127.0.0.1:8008"
    debug_routes_enabled: bool = False

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_model: str = "deepseek-chat"
    deepseek_reasoner_model: str = "deepseek-reasoner"
    deepseek_timeout_seconds: float = 45.0

    we_com_corp_id: str = ""
    we_com_agent_id: str = ""
    we_com_secret: SecretStr | None = None
    we_com_token: str = ""
    we_com_encoding_aes_key: SecretStr | None = None
    owner_we_com_user_id: str = ""

    database_url: str = "postgresql+asyncpg://assistant:assistant@localhost:5432/wecom_assistant"
    redis_url: str = "redis://localhost:6379/0"
    app_encryption_key: SecretStr = Field(default=SecretStr("dev-insecure-change-me"))
    auto_create_tables: bool = True

    searxng_base_url: str = "http://localhost:8080"
    search_enabled: bool = True
    search_timeout_seconds: float = 8.0

    daily_summary_hour: int = 22
    weekly_memory_review_day: str = "sun"
    weekly_memory_review_hour: int = 21
    timezone: str = "Asia/Shanghai"
    memory_retrieval_limit: int = 12
    memory_context_char_budget: int = 1600
    memory_item_char_limit: int = 120
    recent_message_limit: int = 8

    @field_validator("deepseek_base_url", "searxng_base_url", "public_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def has_deepseek_key(self) -> bool:
        value = self.deepseek_api_key.get_secret_value() if self.deepseek_api_key else ""
        return bool(value and not value.startswith("sk-your"))

    @property
    def has_wecom_crypto(self) -> bool:
        aes_key = (
            self.we_com_encoding_aes_key.get_secret_value()
            if self.we_com_encoding_aes_key
            else ""
        )
        return bool(self.we_com_token and aes_key)

    @property
    def has_wecom_send_credentials(self) -> bool:
        secret = self.we_com_secret.get_secret_value() if self.we_com_secret else ""
        return bool(self.we_com_corp_id and self.we_com_agent_id and secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
