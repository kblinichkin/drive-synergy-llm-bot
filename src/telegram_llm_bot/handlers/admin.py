"""
handlers/admin.py — admin-only commands: /stats, /list.

Access control is enforced by checking telegram_id against settings.admin_telegram_ids.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from telegram_llm_bot.config.settings import settings
from telegram_llm_bot.storage.mongo_client import count_active_users, list_active_users

logger = logging.getLogger(__name__)


def _is_admin(update: Update) -> bool:
    user_id = update.effective_user.id
    return user_id in settings.admin_telegram_ids


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats — show total registered member count (admin only)."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ Admin access required.")
        return

    count = await count_active_users()
    await update.message.reply_text(
        f"📊 *Community stats*\n\nActive members: *{count}*",
        parse_mode=ParseMode.MARKDOWN,
    )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /list — list all registered members (admin only)."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ Admin access required.")
        return

    users = await list_active_users(limit=200)

    if not users:
        await update.message.reply_text("No registered members yet.")
        return

    lines = ["*Registered members:*\n"]
    for u in users:
        name = u.get("full_name") or "—"
        username = u.get("telegram_username")
        username_str = f" (@{username})" if username else ""
        tid = u.get("telegram_id", "?")
        registered = u.get("registered_at")
        date_str = registered.strftime("%Y-%m-%d") if registered else "—"
        lines.append(f"• {name}{username_str} — ID: `{tid}` — {date_str}")

    # Split into chunks to avoid Telegram message size limits (4096 chars)
    chunk_size = 50
    for i in range(0, len(lines), chunk_size):
        chunk = "\n".join(lines[i : i + chunk_size])
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
