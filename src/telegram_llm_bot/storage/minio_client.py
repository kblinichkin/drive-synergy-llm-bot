"""
storage/minio_client.py — MinIO object storage client.

Stores and retrieves the original resume files.
Uses the minio Python SDK (sync calls wrapped for async context).
"""
from __future__ import annotations

import asyncio
import io
import logging
from functools import lru_cache

from minio import Minio
from minio.error import S3Error

from telegram_llm_bot.config.settings import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_minio_client() -> Minio:
    return Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def _ensure_bucket_sync() -> None:
    client = _get_minio_client()
    bucket = settings.minio_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info("MinIO bucket '%s' created.", bucket)
    else:
        logger.debug("MinIO bucket '%s' already exists.", bucket)


def ensure_bucket() -> None:
    """Create the resumes bucket if it doesn't exist (sync, call at startup)."""
    _ensure_bucket_sync()


# ─────────────────────────────────────────────────────────────────────────────
# Async-friendly wrappers (run sync SDK calls in a thread executor)
# ─────────────────────────────────────────────────────────────────────────────

async def upload_resume(*, file_bytes: bytes, object_key: str) -> None:
    """Upload resume bytes to MinIO under the given object key."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _upload_sync, file_bytes, object_key)


def _upload_sync(file_bytes: bytes, object_key: str) -> None:
    client = _get_minio_client()
    data = io.BytesIO(file_bytes)
    client.put_object(
        bucket_name=settings.minio_bucket,
        object_name=object_key,
        data=data,
        length=len(file_bytes),
    )
    logger.debug("MinIO upload OK: key=%s size=%d bytes", object_key, len(file_bytes))


async def download_resume(object_key: str) -> bytes:
    """Download resume bytes from MinIO."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _download_sync, object_key)


def _download_sync(object_key: str) -> bytes:
    client = _get_minio_client()
    try:
        response = client.get_object(settings.minio_bucket, object_key)
        data = response.read()
        response.close()
        response.release_conn()
        return data
    except S3Error as exc:
        logger.error("MinIO download failed: key=%s error=%s", object_key, exc)
        raise FileNotFoundError(f"Resume not found in storage: {object_key}") from exc


async def delete_resume(object_key: str) -> None:
    """Delete a resume object from MinIO (no-op if it doesn't exist)."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _delete_sync, object_key)


def _delete_sync(object_key: str) -> None:
    client = _get_minio_client()
    try:
        client.remove_object(settings.minio_bucket, object_key)
        logger.debug("MinIO delete OK: key=%s", object_key)
    except S3Error as exc:
        # "NoSuchKey" and similar are fine during a delete-by-idempotent flow
        logger.warning("MinIO delete failed (ignored): key=%s error=%s", object_key, exc)


async def generate_presigned_url(object_key: str, expires_seconds: int = 3600) -> str:
    """Generate a presigned download URL valid for `expires_seconds`."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _presigned_url_sync, object_key, expires_seconds
    )


def _presigned_url_sync(object_key: str, expires_seconds: int) -> str:
    from datetime import timedelta
    client = _get_minio_client()
    url = client.presigned_get_object(
        bucket_name=settings.minio_bucket,
        object_name=object_key,
        expires=timedelta(seconds=expires_seconds),
    )
    return url
