"""
matching/agent.py — matchmaking agent.

Flow:
  1. Embed the user's query (same model as profiles)
  2. Hybrid search in Weaviate → top candidates
  3. Call OpenRouter LLM to rank and explain candidates
  4. Format results as Telegram-ready message cards

Returns a list of MatchResult objects or raises if no results.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

from openai import AsyncOpenAI

from telegram_llm_bot.config.i18n import t
from telegram_llm_bot.config.prompts import (
    MATCHMAKING_SYSTEM_PROMPT,
    MATCHMAKING_USER_TEMPLATE,
)
from telegram_llm_bot.config.settings import settings
from telegram_llm_bot.pipeline.embedder import embed_query
from telegram_llm_bot.storage.weaviate_client import hybrid_search

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    rank: int
    full_name: str
    headline: str
    reason: str
    skills: list[str]
    telegram_id: int


def _get_openrouter_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        default_headers={
            "HTTP-Referer": settings.openrouter_site_url,
            "X-Title": settings.openrouter_site_name,
        },
    )


async def find_matches(query: str, lang: str = "en") -> list[MatchResult]:
    """
    Full matchmaking pipeline for a user query.
    Returns ranked MatchResult list (may be empty).
    """
    # Step 1: Embed the query
    query_vector = embed_query(query)

    # Step 2: Weaviate hybrid search
    candidates = await hybrid_search(
        query_text=query,
        query_vector=query_vector,
        top_k=settings.search_top_k,
    )

    if not candidates:
        logger.debug("No candidates found in Weaviate for query='%.60s'", query)
        return []

    # Step 3: LLM re-rank
    results = await _llm_rank(query=query, candidates=candidates, lang=lang)
    return results


async def _llm_rank(query: str, candidates: list[dict], lang: str = "en") -> list[MatchResult]:
    """Call OpenRouter to rank candidates and return MatchResult list."""
    # Serialize candidates to compact JSON for the prompt
    candidates_summary = []
    for c in candidates:
        candidates_summary.append({
            "telegram_id": c.get("telegram_id"),
            "full_name": c.get("full_name"),
            "headline": c.get("headline"),
            "skills": c.get("skills", []),
            "industries": c.get("industries", []),
            "experience": c.get("experience"),
            "looking_for": c.get("looking_for"),
            "location": c.get("location"),
        })

    candidates_json = json.dumps(candidates_summary, ensure_ascii=False, indent=2)

    client = _get_openrouter_client()
    t0 = time.monotonic()

    response = await client.chat.completions.create(
        model=settings.openrouter_model,
        messages=[
            {"role": "system", "content": MATCHMAKING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": MATCHMAKING_USER_TEMPLATE.format(
                    query=query,
                    candidates_json=candidates_json,
                    language="Russian" if lang == "ru" else "English",
                ),
            },
        ],
        temperature=0.2,
        max_tokens=1500,
    )

    elapsed = time.monotonic() - t0
    usage = response.usage
    logger.debug(
        "OpenRouter matchmaking: model=%s tokens_in=%s tokens_out=%s latency=%.2fs",
        settings.openrouter_model,
        usage.prompt_tokens if usage else "?",
        usage.completion_tokens if usage else "?",
        elapsed,
    )

    content = response.choices[0].message.content or ""
    return _parse_llm_matches(content)


def _parse_llm_matches(content: str) -> list[MatchResult]:
    """Parse the structured match output from the LLM."""
    content = content.strip()

    if content.upper().startswith("NO_MATCHES") or "NO_MATCHES" in content:
        return []

    results: list[MatchResult] = []

    # Split on --- separator blocks
    blocks = re.split(r"\n?---\n?", content)
    for block in blocks:
        block = block.strip()
        if not block:
            continue

        def _field(key: str) -> str:
            m = re.search(rf"^{key}:\s*(.+)$", block, re.MULTILINE | re.IGNORECASE)
            return m.group(1).strip() if m else ""

        rank_str = _field("RANK")
        name = _field("NAME")
        headline = _field("HEADLINE")
        reason = _field("REASON")
        skills_str = _field("SKILLS")
        tid_str = _field("TELEGRAM_ID")

        if not name or not tid_str:
            continue  # skip malformed block

        try:
            rank = int(rank_str) if rank_str else len(results) + 1
            telegram_id = int(tid_str)
        except ValueError:
            continue

        skills = [s.strip() for s in skills_str.split(",") if s.strip()] if skills_str else []

        results.append(
            MatchResult(
                rank=rank,
                full_name=name,
                headline=headline,
                reason=reason,
                skills=skills,
                telegram_id=telegram_id,
            )
        )

    results.sort(key=lambda r: r.rank)
    return results[: settings.search_return_top]


def format_match_card(match: MatchResult, lang: str = "en") -> str:
    """
    Render a single match as a Telegram message card (Markdown).
    Includes a tg:// deep-link and a /resume_ command.
    """
    skills_str = ", ".join(match.skills[:6]) or "—"

    return (
        f"*{match.rank}. {match.full_name}*\n"
        f"_{match.headline}_\n\n"
        f"{t('match_card_why', lang)} {match.reason}\n"
        f"{t('match_card_skills', lang)} {skills_str}\n\n"
        f"👉 [{t('match_card_contact', lang)}](tg://user?id={match.telegram_id}) | "
        f"/resume\\_{match.telegram_id}"
    )


def format_results_message(matches: list[MatchResult], lang: str = "en") -> str:
    """Combine all match cards into one Telegram message."""
    if not matches:
        return ""
    count = len(matches)
    # Russian pluralisation: 1 → е, 2-4 → я, 5+ → й
    if lang == "ru":
        plural = "е" if count == 1 else ("я" if count < 5 else "й")
    else:
        plural = "es" if count != 1 else ""
    header = t("search_results_header", lang, count=count, plural=plural)
    cards = "\n\n─────────────\n\n".join(format_match_card(m, lang) for m in matches)
    return header + cards
