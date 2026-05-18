"""
Settings — loaded from environment variables via pydantic-settings.
All credentials and configuration live here; never hardcoded elsewhere.
"""
from __future__ import annotations

import logging
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # ── Telegram ─────────────────────────────────────────────────────────────
    telegram_bot_token: str
    bot_name: str = "MatchBot"
    allowed_group_id: int | None = None
    admin_telegram_ids: List[int] = Field(default_factory=list)

    # ── OpenRouter LLM ───────────────────────────────────────────────────────
    openrouter_api_key: str
    # Any model slug available on openrouter.ai, e.g.:
    #   "anthropic/claude-3-haiku"
    #   "openai/gpt-4o-mini"
    #   "mistralai/mistral-7b-instruct"
    openrouter_model: str = "anthropic/claude-3-haiku"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "https://github.com/your-org/matchbot"
    openrouter_site_name: str = "MatchBot"

    # ── Embeddings ────────────────────────────────────────────────────────────
    # Local model name from sentence-transformers (no API key needed)
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dims: int = 384          # 384 for MiniLM, 1536 for text-embedding-3-small

    # ── MongoDB ───────────────────────────────────────────────────────────────
    mongodb_uri: str = "mongodb://mongo:27017"
    mongodb_db: str = "matchbot"

    # ── Weaviate ──────────────────────────────────────────────────────────────
    weaviate_host: str = "weaviate"
    weaviate_port: int = 8080

    # ── MinIO ─────────────────────────────────────────────────────────────────
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "resumes"
    minio_secure: bool = False         # set True when using HTTPS

    # ── Search ────────────────────────────────────────────────────────────────
    search_top_k: int = 10             # candidates fetched from Weaviate
    search_return_top: int = 5         # results shown to user after LLM re-rank

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @field_validator("allowed_group_id", mode="before")
    @classmethod
    def parse_allowed_group_id(cls, v: str | int | None) -> int | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return int(v)

    @field_validator("admin_telegram_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: str | list) -> list[int]:
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, str) and v.strip():
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return []


# Singleton — import this everywhere
settings = Settings()
