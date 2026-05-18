"""
handlers/search.py — /find command and free-text search handler.

Handles:
  /find <query>            — explicit search command (runs immediately)
  /find  (no args)         — prompts the user to type their query (ConversationHandler)
  /resume_<telegram_id>   — download a specific member's resume
  Free-text @BotMention   — search triggered by mentioning the bot in group chat
"""
from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from telegram_llm_bot.config.i18n import t
from telegram_llm_bot.config.settings import settings
from telegram_llm_bot.handlers.i18n_helpers import get_lang
from telegram_llm_bot.matching.agent import find_matches, format_results_message
from telegram_llm_bot.storage.minio_client import download_resume
from telegram_llm_bot.storage.mongo_client import get_user

logger = logging.getLogger(__name__)

# ConversationHandler state
FIND_WAITING_QUERY = 0


async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """
    /find <query> — search for matching community members.

    - With arguments: runs the search immediately.
    - Without arguments: checks registration and prompts for a query.
    """
    lang = await get_lang(update, context)
    user_id = update.effective_user.id

    user_doc = await get_user(user_id)
    if not user_doc:
        await update.message.reply_text(
            t("no_profile", lang), parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    query = " ".join(context.args or []).strip()
    if query:
        # Inline query — run immediately, no conversation needed
        await _run_search(update, context, query)
        return ConversationHandler.END

    # No query — ask for it
    await update.message.reply_text(
        t("find_prompt", lang), parse_mode=ParseMode.MARKDOWN
    )
    return FIND_WAITING_QUERY


async def find_receive_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive the free-text query after the prompt and run the search."""
    query = (update.message.text or "").strip()
    if query:
        await _run_search(update, context, query)
    return ConversationHandler.END


def build_find_handler() -> ConversationHandler:
    """Return the ConversationHandler for the /find flow."""
    return ConversationHandler(
        entry_points=[CommandHandler("find", find_command)],
        states={
            FIND_WAITING_QUERY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, find_receive_query),
            ],
        },
        fallbacks=[CommandHandler("cancel", _find_cancel)],
        conversation_timeout=120,
    )


async def _find_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_lang(update, context)
    await update.message.reply_text(t("cancelled", lang), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


async def group_mention_search(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle free-text messages in group chat that @mention the bot.
    Strips the @mention and uses the remainder as the search query.
    """
    text = update.message.text or ""
    bot_username = context.bot.username or ""
    query = re.sub(rf"@{re.escape(bot_username)}", "", text, flags=re.IGNORECASE).strip()

    if not query:
        await update.message.reply_text(
            f"Hi! Mention me with a search query, e.g.:\n"
            f"@{bot_username} looking for a Python developer open to equity projects",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await _run_search(update, context, query)


async def _run_search(
    update: Update, context: ContextTypes.DEFAULT_TYPE, query: str
) -> None:
    """Shared search execution logic."""
    lang = await get_lang(update, context)
    thinking_msg = await update.message.reply_text(
        t("search_thinking", lang), parse_mode=ParseMode.MARKDOWN
    )

    try:
        matches = await find_matches(query, lang=lang)
        if not matches:
            await thinking_msg.edit_text(
                t("search_no_results", lang), parse_mode=ParseMode.MARKDOWN
            )
            return

        result_text = format_results_message(matches, lang=lang)
        await thinking_msg.edit_text(
            result_text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        logger.info(
            "Search returned %d matches for telegram_id=%d query='%.60s'",
            len(matches),
            update.effective_user.id,
            query,
        )

    except Exception:
        logger.exception(
            "Search error for telegram_id=%d query='%.60s'",
            update.effective_user.id,
            query,
        )
        await thinking_msg.edit_text(
            "⚠️ An error occurred while searching. Please try again later.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def resume_download_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle /resume_<telegram_id> — send the original resume file to the requester.
    """
    text = update.message.text or ""
    match = re.search(r"/resume[_](\d+)", text)
    if not match:
        await update.message.reply_text("❌ Invalid command format.")
        return

    target_id = int(match.group(1))
    target_doc = await get_user(target_id)

    if not target_doc:
        await update.message.reply_text("❌ This member's profile is no longer available.")
        return

    minio_key = target_doc.get("minio_key")
    if not minio_key:
        await update.message.reply_text("❌ Resume file not found.")
        return

    try:
        file_bytes = await download_resume(minio_key)
        filename = minio_key.split("/")[-1]
        await update.message.reply_document(
            document=file_bytes,
            filename=filename,
            caption=f"📄 Resume of {target_doc.get('full_name', 'member')}",
        )
    except FileNotFoundError:
        await update.message.reply_text("❌ Resume file not found in storage.")
    except Exception:
        logger.exception("Failed to send resume for target_id=%d", target_id)
        await update.message.reply_text("⚠️ Could not retrieve the resume. Please try again later.")
