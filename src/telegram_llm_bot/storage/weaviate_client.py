"""
storage/weaviate_client.py — Weaviate v4 client wrapper.

Handles:
  - Schema / collection bootstrap (idempotent)
  - Profile upsert (insert or replace by telegram_id)
  - Hybrid search (vector + BM25)
  - Profile deletion by UUID
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import weaviate
import weaviate.classes as wvc
from weaviate.classes.config import Configure, DataType, Property
from weaviate.classes.query import MetadataQuery

from telegram_llm_bot.config.settings import settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "MemberProfile"

# ─────────────────────────────────────────────────────────────────────────────
# Connection helpers
# ─────────────────────────────────────────────────────────────────────────────

_client: weaviate.WeaviateClient | None = None


def get_client() -> weaviate.WeaviateClient:
    global _client
    if _client is None or not _client.is_connected():
        _client = weaviate.connect_to_local(
            host=settings.weaviate_host,
            port=settings.weaviate_port,
        )
    return _client


def close_client() -> None:
    global _client
    if _client and _client.is_connected():
        _client.close()
        _client = None


# ─────────────────────────────────────────────────────────────────────────────
# Schema bootstrap
# ─────────────────────────────────────────────────────────────────────────────

def ensure_schema() -> None:
    """Create the MemberProfile collection if it doesn't exist (idempotent)."""
    client = get_client()

    if client.collections.exists(COLLECTION_NAME):
        logger.debug("Weaviate collection '%s' already exists.", COLLECTION_NAME)
        return

    logger.info("Creating Weaviate collection '%s'.", COLLECTION_NAME)
    client.collections.create(
        name=COLLECTION_NAME,
        description="Community member profiles for matchmaking",
        vectorizer_config=Configure.Vectorizer.none(),   # we supply vectors ourselves
        properties=[
            Property(name="telegram_id",  data_type=DataType.INT),
            Property(name="full_name",    data_type=DataType.TEXT),
            Property(name="headline",     data_type=DataType.TEXT),
            Property(name="skills",       data_type=DataType.TEXT_ARRAY),
            Property(name="industries",   data_type=DataType.TEXT_ARRAY),
            Property(name="experience",   data_type=DataType.TEXT),
            Property(name="looking_for",  data_type=DataType.TEXT),
            Property(name="location",     data_type=DataType.TEXT),
            Property(name="resume_text",  data_type=DataType.TEXT),
        ],
    )
    logger.info("Collection '%s' created.", COLLECTION_NAME)


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# The weaviate v4 Python client is synchronous. We wrap each call in
# run_in_executor so the asyncio event loop is never blocked.
# ─────────────────────────────────────────────────────────────────────────────

async def _run_sync(func, /, *args, **kwargs):
    loop = asyncio.get_running_loop()
    if kwargs:
        from functools import partial
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))
    return await loop.run_in_executor(None, func, *args)


def _upsert_member_profile_sync(
    telegram_id: int,
    profile_fields: dict,
    vector: list[float],
) -> uuid.UUID:
    client = get_client()
    collection = client.collections.get(COLLECTION_NAME)

    # Check for existing entry and delete it so we can insert fresh
    existing = collection.query.fetch_objects(
        filters=wvc.query.Filter.by_property("telegram_id").equal(telegram_id),
        limit=1,
    )
    if existing.objects:
        existing_uuid = existing.objects[0].uuid
        logger.debug(
            "Deleting existing Weaviate profile uuid=%s for telegram_id=%d",
            existing_uuid,
            telegram_id,
        )
        collection.data.delete_by_id(existing_uuid)

    props = {
        "telegram_id":  telegram_id,
        "full_name":    profile_fields.get("full_name", ""),
        "headline":     profile_fields.get("headline", ""),
        "skills":       profile_fields.get("skills", []),
        "industries":   profile_fields.get("industries", []),
        "experience":   profile_fields.get("experience", ""),
        "looking_for":  profile_fields.get("looking_for", ""),
        "location":     profile_fields.get("location", ""),
        "resume_text":  profile_fields.get("resume_text", ""),
    }

    new_uuid = collection.data.insert(properties=props, vector=vector)
    logger.debug("Inserted Weaviate profile uuid=%s", new_uuid)
    return new_uuid


async def upsert_member_profile(
    *,
    telegram_id: int,
    profile_fields: dict,
    vector: list[float],
) -> uuid.UUID:
    """Insert or replace a member profile. Non-blocking wrapper."""
    return await _run_sync(
        _upsert_member_profile_sync, telegram_id, profile_fields, vector
    )


def _get_profile_uuid_sync(telegram_id: int) -> uuid.UUID | None:
    client = get_client()
    collection = client.collections.get(COLLECTION_NAME)
    result = collection.query.fetch_objects(
        filters=wvc.query.Filter.by_property("telegram_id").equal(telegram_id),
        limit=1,
    )
    if result.objects:
        return result.objects[0].uuid
    return None


async def get_profile_uuid_by_telegram_id(telegram_id: int) -> uuid.UUID | None:
    """Return the Weaviate UUID for a telegram_id, or None if not found."""
    return await _run_sync(_get_profile_uuid_sync, telegram_id)


def _delete_member_profile_sync(weaviate_uuid: str) -> None:
    client = get_client()
    collection = client.collections.get(COLLECTION_NAME)
    collection.data.delete_by_id(uuid.UUID(weaviate_uuid))
    logger.debug("Deleted Weaviate profile uuid=%s", weaviate_uuid)


async def delete_member_profile(weaviate_uuid: str) -> None:
    """Delete a profile by its UUID string. Non-blocking wrapper."""
    await _run_sync(_delete_member_profile_sync, weaviate_uuid)


def _hybrid_search_sync(
    query_text: str,
    query_vector: list[float],
    limit: int,
) -> list[dict[str, Any]]:
    client = get_client()
    collection = client.collections.get(COLLECTION_NAME)

    results = collection.query.hybrid(
        query=query_text,
        vector=query_vector,
        limit=limit,
        return_metadata=MetadataQuery(score=True),
        return_properties=[
            "telegram_id",
            "full_name",
            "headline",
            "skills",
            "industries",
            "experience",
            "looking_for",
            "location",
        ],
    )

    hits: list[dict[str, Any]] = []
    for obj in results.objects:
        item = dict(obj.properties)
        item["_score"] = obj.metadata.score if obj.metadata else 0.0
        item["_uuid"] = str(obj.uuid)
        hits.append(item)

    logger.debug(
        "Hybrid search returned %d hits for query='%.60s'", len(hits), query_text
    )
    return hits


def _fetch_all_profiles_sync(limit: int) -> list[dict[str, Any]]:
    client = get_client()
    collection = client.collections.get(COLLECTION_NAME)
    results = collection.query.fetch_objects(
        limit=limit,
        # Intentionally excludes experience and resume_text — too large for bulk analysis
        return_properties=["headline", "skills", "industries", "looking_for", "location"],
    )
    return [dict(obj.properties) for obj in results.objects]


async def fetch_all_profiles(limit: int = 500) -> list[dict[str, Any]]:
    """Return compact profiles (no heavy text fields) for bulk analysis."""
    return await _run_sync(_fetch_all_profiles_sync, limit)


async def hybrid_search(
    *,
    query_text: str,
    query_vector: list[float],
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """Hybrid (vector + BM25) search. Non-blocking wrapper."""
    limit = top_k or settings.search_top_k
    return await _run_sync(_hybrid_search_sync, query_text, query_vector, limit)
