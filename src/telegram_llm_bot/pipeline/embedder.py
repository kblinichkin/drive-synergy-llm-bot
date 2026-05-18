"""
pipeline/embedder.py — generate embedding vectors for profile text.

Uses sentence-transformers (local, no API key required).
The model is loaded once and cached for the process lifetime.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import List

from telegram_llm_bot.config.settings import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_model():
    """Load and cache the embedding model (lazy, loads on first call)."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed. "
            "Add 'sentence-transformers' to pyproject.toml."
        ) from exc

    logger.info("Loading embedding model: %s", settings.embedding_model)
    model = SentenceTransformer(settings.embedding_model)
    logger.info("Embedding model loaded (dims=%d).", settings.embedding_dims)
    return model


def embed_text(text: str) -> List[float]:
    """
    Embed a single string and return a flat list of floats.
    The model is loaded once on first call.
    """
    model = _get_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def build_profile_embed_text(profile_dict: dict) -> str:
    """
    Construct the string that represents a profile for embedding.
    Mirrors the design decision in CLAUDE.md: headline + skills + experience + looking_for.
    """
    skills_str = ", ".join(profile_dict.get("skills") or [])
    parts = [
        profile_dict.get("headline") or "",
        skills_str,
        profile_dict.get("experience") or "",
        profile_dict.get("looking_for") or "",
    ]
    return "\n".join(p for p in parts if p.strip())


def embed_profile(profile_dict: dict) -> List[float]:
    """
    Create the embedding vector for a member profile.
    Call this before inserting into Weaviate.
    """
    text = build_profile_embed_text(profile_dict)
    if not text.strip():
        raise ValueError("Profile has no embeddable text fields.")
    return embed_text(text)


def embed_query(query: str) -> List[float]:
    """Embed a free-text search query (same model, same space as profiles)."""
    return embed_text(query)
