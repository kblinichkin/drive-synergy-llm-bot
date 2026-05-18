"""
storage/mongo_client.py — MongoDB (via motor async driver) client.

Stores the user registry: telegram_id → profile metadata (no file bytes here).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import motor.motor_asyncio
from pymongo import ASCENDING, IndexModel

from telegram_llm_bot.config.settings import settings

logger = logging.getLogger(__name__)

_motor_client: motor.motor_asyncio.AsyncIOMotorClient | None = None


def get_db() -> motor.motor_asyncio.AsyncIOMotorDatabase:
    global _motor_client
    if _motor_client is None:
        _motor_client = motor.motor_asyncio.AsyncIOMotorClient(settings.mongodb_uri)
    return _motor_client[settings.mongodb_db]


async def ensure_indexes() -> None:
    """Create a unique index on telegram_id (idempotent)."""
    db = get_db()
    await db.users.create_indexes(
        [IndexModel([("telegram_id", ASCENDING)], unique=True, name="telegram_id_unique")]
    )
    logger.debug("MongoDB indexes ensured.")


# ─────────────────────────────────────────────────────────────────────────────
# CRUD helpers
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_user(
    *,
    telegram_id: int,
    telegram_username: str | None,
    full_name: str,
    minio_key: str,
    weaviate_uuid: str,
    now: datetime | None = None,
) -> None:
    """Insert or update a user document."""
    db = get_db()
    if now is None:
        now = datetime.now(tz=timezone.utc)

    await db.users.update_one(
        {"telegram_id": telegram_id},
        {
            "$set": {
                "telegram_username": telegram_username,
                "full_name": full_name,
                "profile_status": "active",
                "minio_key": minio_key,
                "weaviate_uuid": weaviate_uuid,
                "updated_at": now,
            },
            "$setOnInsert": {
                "registered_at": now,
            },
        },
        upsert=True,
    )
    logger.debug("MongoDB upsert OK: telegram_id=%d", telegram_id)


async def get_user(telegram_id: int) -> dict[str, Any] | None:
    """Return the user document or None if not found / deleted."""
    db = get_db()
    doc = await db.users.find_one(
        {"telegram_id": telegram_id, "profile_status": "active"}
    )
    return doc


async def delete_user(telegram_id: int) -> None:
    """Soft-delete by setting profile_status = 'deleted'."""
    db = get_db()
    await db.users.update_one(
        {"telegram_id": telegram_id},
        {"$set": {"profile_status": "deleted", "updated_at": datetime.now(tz=timezone.utc)}},
    )
    logger.debug("MongoDB soft-delete: telegram_id=%d", telegram_id)


async def get_user_language(telegram_id: int) -> str | None:
    """Return the stored language preference for a user, or None if not set."""
    db = get_db()
    doc = await db.users.find_one(
        {"telegram_id": telegram_id},
        {"lang": 1},
    )
    return doc.get("lang") if doc else None


async def set_user_language(telegram_id: int, lang: str) -> None:
    """Persist a language preference for a user (upserts the field)."""
    db = get_db()
    await db.users.update_one(
        {"telegram_id": telegram_id},
        {"$set": {"lang": lang}},
        upsert=True,
    )
    logger.debug("Language set: telegram_id=%d lang=%s", telegram_id, lang)


async def count_active_users() -> int:
    """Return the number of active registered members."""
    db = get_db()
    return await db.users.count_documents({"profile_status": "active"})


async def list_active_users(limit: int = 200) -> list[dict[str, Any]]:
    """Return a list of active user documents (for admin use)."""
    db = get_db()
    cursor = db.users.find(
        {"profile_status": "active"},
        {"telegram_id": 1, "telegram_username": 1, "full_name": 1, "registered_at": 1},
    ).sort("registered_at", -1).limit(limit)
    return await cursor.to_list(length=limit)
