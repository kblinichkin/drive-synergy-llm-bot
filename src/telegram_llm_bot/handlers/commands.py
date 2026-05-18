"""
handlers/commands.py — basic bot commands:
  /start, /help, /mystatus, /delete, /cancel, /language
"""
from __future__ import annotations

import logging
import time
from collections import Counter

from openai import AsyncOpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from telegram_llm_bot.config.i18n import SUPPORTED_LANGS, t
from telegram_llm_bot.config.prompts import SUMMARY_SYSTEM_PROMPT, SUMMARY_USER_TEMPLATE
from telegram_llm_bot.config.settings import settings
from telegram_llm_bot.handlers.i18n_helpers import get_lang, set_lang_cache, sync_commands
from telegram_llm_bot.storage.minio_client import delete_resume
from telegram_llm_bot.storage.mongo_client import (
    count_active_users,
    delete_user,
    get_user,
    set_user_language,
)
from telegram_llm_bot.storage.weaviate_client import delete_member_profile, fetch_all_profiles

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — welcome message in the user's language."""
    lang = await get_lang(update, context)
    await sync_commands(context, update.effective_chat.id, lang)
    await update.message.reply_text(
        t("start", lang, bot_name=settings.bot_name),
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help."""
    lang = await get_lang(update, context)
    await update.message.reply_text(
        t("help", lang, bot_name=settings.bot_name),
        parse_mode=ParseMode.MARKDOWN,
    )


async def mystatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /mystatus — show user's current profile summary."""
    lang = await get_lang(update, context)
    user_id = update.effective_user.id
    doc = await get_user(user_id)

    if not doc:
        await update.message.reply_text(
            t("no_profile", lang), parse_mode=ParseMode.MARKDOWN
        )
        return

    registered = doc.get("registered_at")
    updated = doc.get("updated_at")
    username = doc.get("telegram_username")

    await update.message.reply_text(
        t(
            "mystatus_active",
            lang,
            full_name=doc.get("full_name", "—"),
            username=f"@{username}" if username else "—",
            registered=registered.strftime("%Y-%m-%d") if registered else "—",
            updated=updated.strftime("%Y-%m-%d") if updated else "—",
        ),
        parse_mode=ParseMode.MARKDOWN,
    )


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete — remove user's profile."""
    lang = await get_lang(update, context)
    user_id = update.effective_user.id
    doc = await get_user(user_id)

    if not doc:
        await update.message.reply_text(
            t("no_profile", lang), parse_mode=ParseMode.MARKDOWN
        )
        return

    weaviate_uuid = doc.get("weaviate_uuid")
    if weaviate_uuid:
        try:
            await delete_member_profile(weaviate_uuid)
        except Exception as exc:
            logger.warning("Could not delete Weaviate profile uuid=%s: %s", weaviate_uuid, exc)

    minio_key = doc.get("minio_key")
    if minio_key:
        try:
            await delete_resume(minio_key)
        except Exception as exc:
            logger.warning("Could not delete MinIO object key=%s: %s", minio_key, exc)

    await delete_user(user_id)
    await update.message.reply_text(
        t("profile_deleted", lang), parse_mode=ParseMode.MARKDOWN
    )
    logger.info("Profile deleted: telegram_id=%d", user_id)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel — terminate any active conversation flow."""
    lang = await get_lang(update, context)
    await update.message.reply_text(
        t("cancelled", lang), parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


def _aggregate_profiles(profiles: list[dict]) -> dict:
    """
    Reduce a list of raw profiles into compact frequency tables and samples.
    This is what gets sent to the LLM — not the raw profiles.
    """
    skills_counter: Counter = Counter()
    industries_counter: Counter = Counter()
    locations_counter: Counter = Counter()
    looking_for_samples: list[str] = []
    headline_samples: list[str] = []

    for p in profiles:
        for skill in (p.get("skills") or []):
            skills_counter[skill.strip()] += 1
        for ind in (p.get("industries") or []):
            industries_counter[ind.strip()] += 1
        loc = (p.get("location") or "").strip()
        if loc:
            locations_counter[loc] += 1
        lf = (p.get("looking_for") or "").strip()
        if lf and len(looking_for_samples) < 12:
            looking_for_samples.append(f"• {lf[:120]}")
        hl = (p.get("headline") or "").strip()
        if hl and len(headline_samples) < 12:
            headline_samples.append(f"• {hl[:120]}")

    def _format_counter(c: Counter, top: int) -> str:
        return "\n".join(f"  {k}: {v}" for k, v in c.most_common(top)) or "  —"

    return {
        "top_skills":         _format_counter(skills_counter, 25),
        "top_industries":     _format_counter(industries_counter, 15),
        "locations":          _format_counter(locations_counter, 15),
        "looking_for_samples": "\n".join(looking_for_samples) or "  —",
        "headline_samples":   "\n".join(headline_samples) or "  —",
    }


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /summary — LLM-generated community overview + member count."""
    lang = await get_lang(update, context)

    thinking_msg = await update.message.reply_text(
        t("summary_thinking", lang), parse_mode=ParseMode.MARKDOWN
    )

    try:
        count = await count_active_users()

        if count == 0:
            await thinking_msg.edit_text(t("summary_empty", lang), parse_mode=ParseMode.MARKDOWN)
            return

        profiles = await fetch_all_profiles()
        agg = _aggregate_profiles(profiles)
        language_label = "Russian" if lang == "ru" else "English"

        client = AsyncOpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            default_headers={
                "HTTP-Referer": settings.openrouter_site_url,
                "X-Title": settings.openrouter_site_name,
            },
        )

        t0 = time.monotonic()
        response = await client.chat.completions.create(
            model=settings.openrouter_model,
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT.format(language=language_label)},
                {"role": "user", "content": SUMMARY_USER_TEMPLATE.format(count=count, **agg)},
            ],
            temperature=0.3,
            max_tokens=600,
        )
        elapsed = time.monotonic() - t0
        logger.debug("Summary LLM call: %.2fs tokens_in=%s tokens_out=%s",
                     elapsed,
                     response.usage.prompt_tokens if response.usage else "?",
                     response.usage.completion_tokens if response.usage else "?")

        analysis = response.choices[0].message.content or ""
        header = t("summary_header", lang, count=count)
        await thinking_msg.edit_text(
            header + analysis,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception:
        logger.exception("Summary command failed for telegram_id=%d", update.effective_user.id)
        await thinking_msg.edit_text(t("summary_error", lang), parse_mode=ParseMode.MARKDOWN)


_LANGUAGE_LABELS = {"en": "🇬🇧 English", "ru": "🇷🇺 Русский"}

_LANG_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton(label, callback_data=f"set_lang:{code}")]
     for code, label in _LANGUAGE_LABELS.items()]
)


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /language — show an inline keyboard to pick a language."""
    current_lang = await get_lang(update, context)

    # If a code was passed directly (e.g. /language ru), apply it immediately
    if context.args:
        requested = context.args[0].strip().lower()
        if requested not in SUPPORTED_LANGS:
            await update.message.reply_text(
                t("language_unknown", current_lang), parse_mode=ParseMode.MARKDOWN
            )
            return
        await _apply_language(update.effective_user.id, update.effective_chat.id,
                               context, requested)
        await update.message.reply_text(
            t("language_changed", requested), parse_mode=ParseMode.MARKDOWN
        )
        return

    # No argument — show the picker
    prompt = {"en": "🌐 Choose your language:", "ru": "🌐 Выберите язык:"}
    await update.message.reply_text(
        prompt.get(current_lang, prompt["en"]),
        reply_markup=_LANG_KEYBOARD,
    )


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button press from the language picker."""
    query = update.callback_query
    await query.answer()

    requested = query.data.removeprefix("set_lang:")
    if requested not in SUPPORTED_LANGS:
        return

    await _apply_language(query.from_user.id, query.message.chat.id, context, requested)
    await query.edit_message_text(
        t("language_changed", requested), parse_mode=ParseMode.MARKDOWN
    )
    logger.info("Language changed via button: telegram_id=%d lang=%s", query.from_user.id, requested)


async def _apply_language(
    user_id: int,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> None:
    """Persist language, update cache, and sync the command menu."""
    await set_user_language(user_id, lang)
    set_lang_cache(context, lang)
    await sync_commands(context, chat_id, lang)
