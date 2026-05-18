"""
pipeline/extractor.py — call OpenRouter LLM to extract structured profile fields
from raw resume text.

Uses the openai SDK pointed at the OpenRouter base URL (OpenAI-compatible).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, field_validator

from telegram_llm_bot.config.prompts import (
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_TEMPLATE,
)
from telegram_llm_bot.config.settings import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic model for validated extracted fields
# ─────────────────────────────────────────────────────────────────────────────

class ExtractedProfile(BaseModel):
    full_name: str | None = None
    headline: str | None = None
    skills: list[str] = []
    industries: list[str] = []
    experience: str | None = None
    looking_for: str | None = None
    location: str | None = None

    @field_validator("skills", "industries", mode="before")
    @classmethod
    def ensure_list(cls, v: Any) -> list:
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return list(v)

    def to_weaviate_dict(self) -> dict:
        """Return a dict matching the Weaviate MemberProfile schema."""
        return {
            "full_name": self.full_name or "",
            "headline": self.headline or "",
            "skills": self.skills,
            "industries": self.industries,
            "experience": self.experience or "",
            "looking_for": self.looking_for or "",
            "location": self.location or "",
        }

    def format_preview(self) -> str:
        """Human-readable preview for Telegram confirmation message."""
        skills_str = ", ".join(self.skills[:10]) or "—"
        industries_str = ", ".join(self.industries[:5]) or "—"
        return (
            f"👤 *Name:* {self.full_name or '—'}\n"
            f"💼 *Headline:* {self.headline or '—'}\n"
            f"🛠 *Skills:* {skills_str}\n"
            f"🏭 *Industries:* {industries_str}\n"
            f"📍 *Location:* {self.location or '—'}\n\n"
            f"📝 *Experience:*\n{self.experience or '—'}\n\n"
            f"🤝 *Looking for:*\n{self.looking_for or '—'}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# OpenRouter client
# ─────────────────────────────────────────────────────────────────────────────

def _get_openrouter_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        default_headers={
            # OpenRouter recommends these headers for rate-limit tracking
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_site_name,
        },
    )


async def extract_profile_fields(raw_text: str) -> ExtractedProfile:
    """
    Call OpenRouter LLM to extract structured profile fields from resume text.
    Returns a validated ExtractedProfile.
    """
    # Truncate very long resumes to stay within context limits
    truncated = raw_text[:12_000]

    client = _get_openrouter_client()
    t0 = time.monotonic()

    response = await client.chat.completions.create(
        model=settings.openrouter_model,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": EXTRACTION_USER_TEMPLATE.format(raw_text=truncated),
            },
        ],
        temperature=0.0,
        max_tokens=1024,
    )

    elapsed = time.monotonic() - t0
    usage = response.usage
    logger.debug(
        "OpenRouter extraction: model=%s tokens_in=%s tokens_out=%s latency=%.2fs",
        settings.openrouter_model,
        usage.prompt_tokens if usage else "?",
        usage.completion_tokens if usage else "?",
        elapsed,
    )

    content = response.choices[0].message.content or ""
    return _parse_json_response(content)


def _parse_json_response(content: str) -> ExtractedProfile:
    """
    Parse the LLM response as JSON.
    Strips markdown code fences if the model accidentally added them.
    """
    # Strip ```json ... ``` or ``` ... ``` wrappers
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        # remove first and last fence lines
        content = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        )

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse LLM JSON response: %s\nRaw: %s", exc, content[:500])
        raise ValueError(
            f"The LLM returned invalid JSON. Cannot parse profile fields. "
            f"Error: {exc}"
        ) from exc

    return ExtractedProfile.model_validate(data)
