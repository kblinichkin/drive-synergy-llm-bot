"""
pipeline/ingestion.py — orchestrate the full resume ingestion pipeline.

Steps:
  1. parser.py   — extract raw text from PDF / DOC / DOCX bytes
  2. extractor.py — LLM call (OpenRouter) to get structured profile fields
  3. embedder.py  — generate embedding vector
  4. storage/*    — persist to Weaviate (vectors+fields), MongoDB (metadata), MinIO (file)

Returns the final ExtractedProfile so the handler can show a preview.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from telegram_llm_bot.config.settings import settings
from telegram_llm_bot.pipeline.embedder import embed_profile
from telegram_llm_bot.pipeline.extractor import ExtractedProfile, extract_profile_fields
from telegram_llm_bot.pipeline.parser import extract_text
from telegram_llm_bot.storage.minio_client import upload_resume
from telegram_llm_bot.storage.mongo_client import upsert_user
from telegram_llm_bot.storage.weaviate_client import upsert_member_profile

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    """
    The full output of the resume ingestion pipeline.
    Held in conversation state between the 'preview' and 'store' steps.
    """
    profile: ExtractedProfile
    profile_dict: dict
    vector: list[float]
    file_bytes: bytes
    filename: str


async def ingest_resume(
    *,
    file_bytes: bytes,
    filename: str,
    mime_type: str | None,
    telegram_id: int,
    telegram_username: str | None,
) -> IngestionResult:
    """
    Run the full ingestion pipeline for a new or updated resume.

    Returns an IngestionResult (profile + profile_dict + vector + file bytes + filename).
    Raises on any step failure (caller should surface user-friendly message).
    """
    logger.info(
        "Ingestion start: telegram_id=%d filename=%s mime=%s",
        telegram_id,
        filename,
        mime_type,
    )

    # ── Step 1: Parse raw text ────────────────────────────────────────────────
    logger.debug("Step 1: parsing text from %s", filename)
    raw_text = extract_text(file_bytes, filename, mime_type)
    logger.debug("Extracted %d chars of text.", len(raw_text))

    # ── Step 2: LLM extraction ────────────────────────────────────────────────
    logger.debug("Step 2: extracting profile fields via OpenRouter")
    profile: ExtractedProfile = await extract_profile_fields(raw_text)
    logger.debug("Extracted profile: name=%s headline=%s", profile.full_name, profile.headline)

    # ── Step 3: Embed ─────────────────────────────────────────────────────────
    logger.debug("Step 3: embedding profile")
    profile_dict = profile.to_weaviate_dict()
    # Add full text for RAG retrieval
    profile_dict["resume_text"] = raw_text[:8000]  # cap at 8k chars for storage
    profile_dict["telegram_id"] = telegram_id

    vector = embed_profile(profile_dict)
    logger.debug("Embedding generated (%d dims).", len(vector))

    return IngestionResult(
        profile=profile,
        profile_dict=profile_dict,
        vector=vector,
        file_bytes=file_bytes,
        filename=filename,
    )


async def store_profile(
    *,
    profile: ExtractedProfile,
    profile_dict: dict,
    vector: list[float],
    file_bytes: bytes,
    filename: str,
    telegram_id: int,
    telegram_username: str | None,
) -> None:
    """
    Persist a confirmed profile to all three stores.
    Call this after the user confirms the extracted preview.
    """
    now = datetime.now(tz=timezone.utc)

    # ── Step 4a: MinIO — store original file ─────────────────────────────────
    logger.debug("Storing file in MinIO: telegram_id=%d", telegram_id)
    minio_key = f"resumes/{telegram_id}/{filename}"
    await upload_resume(file_bytes=file_bytes, object_key=minio_key)
    logger.debug("MinIO upload OK: key=%s", minio_key)

    # ── Step 4b: Weaviate — upsert vector + fields ───────────────────────────
    logger.debug("Upserting profile in Weaviate: telegram_id=%d", telegram_id)
    weaviate_uuid = await upsert_member_profile(
        telegram_id=telegram_id,
        profile_fields=profile_dict,
        vector=vector,
    )
    logger.debug("Weaviate upsert OK: uuid=%s", weaviate_uuid)

    # ── Step 4c: MongoDB — upsert user registry ───────────────────────────────
    logger.debug("Upserting user registry in MongoDB: telegram_id=%d", telegram_id)
    await upsert_user(
        telegram_id=telegram_id,
        telegram_username=telegram_username,
        full_name=profile.full_name or "",
        minio_key=minio_key,
        weaviate_uuid=str(weaviate_uuid),
        now=now,
    )
    logger.info("Ingestion complete: telegram_id=%d weaviate_uuid=%s", telegram_id, weaviate_uuid)
