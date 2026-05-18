"""
handlers/i18n_helpers.py — language resolution for incoming updates.

Resolution order:
  1. context.user_data["lang"]  — in-memory cache (fast, cleared on restart)
  2. MongoDB users.lang         — persisted preference set via /language
  3. update.effective_user.language_code — Telegram app locale
  4. "en"                       — hard fallback
"""
from __future__ import annotations

import logging

from telegram import BotCommandScopeChat, Update
from telegram.ext import ContextTypes

from telegram_llm_bot.config.i18n import COMMANDS, DEFAULT_LANG, SUPPORTED_LANGS
from telegram_llm_bot.storage.mongo_client import get_user_language

logger = logging.getLogger(__name__)

_LANG_CACHE_KEY = "lang"


async def get_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Resolve the best language code for this user."""
    # 1. In-memory cache
    cached = context.user_data.get(_LANG_CACHE_KEY)
    if cached and cached in SUPPORTED_LANGS:
        return cached

    user = update.effective_user
    if user is None:
        return DEFAULT_LANG

    # 2. Stored preference in MongoDB
    try:
        stored = await get_user_language(user.id)
        if stored and stored in SUPPORTED_LANGS:
            context.user_data[_LANG_CACHE_KEY] = stored
            return stored
    except Exception as exc:
        logger.debug("Could not fetch language from DB for user %d: %s", user.id, exc)

    # 3. Telegram app locale (e.g. "ru", "en-GB" → take first two chars)
    tg_lang = (user.language_code or "")[:2].lower()
    if tg_lang in SUPPORTED_LANGS:
        context.user_data[_LANG_CACHE_KEY] = tg_lang
        return tg_lang

    # 4. Hard fallback
    return DEFAULT_LANG


def set_lang_cache(context: ContextTypes.DEFAULT_TYPE, lang: str) -> None:
    """Update the in-memory cache after a /language change."""
    context.user_data[_LANG_CACHE_KEY] = lang


async def sync_commands(context: ContextTypes.DEFAULT_TYPE, chat_id: int, lang: str) -> None:
    """Push language-specific command descriptions to a specific chat."""
    commands = COMMANDS.get(lang, COMMANDS[DEFAULT_LANG])
    await context.bot.set_my_commands(
        commands,
        scope=BotCommandScopeChat(chat_id=chat_id),
    )
