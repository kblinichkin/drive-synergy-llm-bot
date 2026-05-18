"""
main.py — entry point for the MatchBot Telegram application.

Bootstraps all storage backends, registers all handlers, and starts polling.
"""
from __future__ import annotations

import logging
import logging.config
import os
import re
import sys

from telegram import BotCommand
from telegram_llm_bot.config.i18n import COMMANDS
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from telegram_llm_bot.config.settings import settings
from telegram_llm_bot.handlers.admin import list_command, stats_command
from telegram_llm_bot.handlers.fallback import unknown_message_handler
from telegram_llm_bot.handlers.commands import (
    cancel_command,
    delete_command,
    help_command,
    language_callback,
    language_command,
    mystatus_command,
    start_command,
    summary_command,
)
from telegram_llm_bot.handlers.registration import build_registration_handler
from telegram_llm_bot.handlers.search import (
    build_find_handler,
    group_mention_search,
    resume_download_command,
)
from telegram_llm_bot.storage.minio_client import ensure_bucket
from telegram_llm_bot.storage.mongo_client import ensure_indexes
from telegram_llm_bot.storage.weaviate_client import close_client, ensure_schema

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """
    Configure logging from logging.conf (INI format).
    Falls back to a sensible stdout-only config if the file is missing
    or malformed, so a bad logging.conf never crashes the bot.
    """
    os.makedirs("logs", exist_ok=True)
    try:
        logging.config.fileConfig("logging.conf", disable_existing_loggers=False)
    except Exception as exc:  # FileNotFoundError, KeyError, configparser errors, …
        logging.basicConfig(
            level=logging.INFO,
            stream=sys.stdout,
            format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        )
        logging.getLogger(__name__).warning(
            "Could not load logging.conf (%s); using basicConfig.", exc
        )


async def _post_init(application: Application) -> None:
    """Run after the bot connects — bootstrap storage and set bot commands."""
    logger.info("Bootstrapping storage backends...")

    # MongoDB
    await ensure_indexes()
    logger.info("MongoDB indexes ensured.")

    # Weaviate
    ensure_schema()
    logger.info("Weaviate schema ensured.")

    # MinIO
    ensure_bucket()
    logger.info("MinIO bucket ensured.")

    # Register default (English) commands globally; per-chat overrides are set
    # dynamically in /start and /language via BotCommandScopeChat.
    await application.bot.set_my_commands(COMMANDS["en"])   # default (English) global list
    logger.info("Bot commands registered.")
    logger.info("MatchBot ready ✓")


async def _post_shutdown(application: Application) -> None:
    """Clean up connections on shutdown."""
    close_client()
    logger.info("Weaviate client closed.")


def build_application() -> Application:
    """Construct the Application with all handlers attached."""
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    # ── Registration FSM ──────────────────────────────────────────────────────
    app.add_handler(build_registration_handler())

    # ── Basic commands ─────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",    start_command))
    app.add_handler(CommandHandler("help",     help_command))
    app.add_handler(CommandHandler("mystatus", mystatus_command))
    app.add_handler(CommandHandler("delete",   delete_command))
    app.add_handler(CommandHandler("cancel",   cancel_command))
    app.add_handler(CommandHandler("summary",  summary_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CallbackQueryHandler(language_callback, pattern=r"^set_lang:"))

    # ── Search ─────────────────────────────────────────────────────────────────
    app.add_handler(build_find_handler())

    # /resume_<id> dynamic command (matches /resume_123456789)
    app.add_handler(
        MessageHandler(
            filters.Regex(re.compile(r"^/resume_\d+", re.IGNORECASE)),
            resume_download_command,
        )
    )

    # Free-text @BotMention in group chats
    if settings.allowed_group_id:
        app.add_handler(
            MessageHandler(
                filters.Chat(settings.allowed_group_id)
                & filters.TEXT
                & filters.Entity("mention"),
                group_mention_search,
            )
        )

    # ── Admin commands ─────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("list",  list_command))

    # ── Fallback — must be last ────────────────────────────────────────────────
    app.add_handler(unknown_message_handler())

    return app


def main() -> None:
    _setup_logging()
    logger.info(
        "Starting %s (model=%s)...",
        settings.bot_name,
        settings.openrouter_model,
    )
    app = build_application()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
