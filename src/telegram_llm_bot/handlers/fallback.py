"""
handlers/fallback.py — catch-all handler for unrecognised messages.

Registered last so it only fires when no other handler claimed the update.
"""
from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, MessageHandler, filters

from telegram_llm_bot.config.i18n import t
from telegram_llm_bot.handlers.i18n_helpers import get_lang


async def _unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await get_lang(update, context)
    await update.message.reply_text(
        t("unknown_message", lang), parse_mode=ParseMode.MARKDOWN
    )


def unknown_message_handler() -> MessageHandler:
    """Return a handler that catches all non-command text messages."""
    return MessageHandler(filters.TEXT & ~filters.COMMAND, _unknown_message)
