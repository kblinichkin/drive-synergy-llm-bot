"""
handlers/registration.py — FSM ConversationHandler for /register.

States:
  UPLOAD_RESUME    — waiting for user to send a file
  CONFIRM_PROFILE  — showing extracted preview, waiting for yes/no

Works for both new registrations and re-uploads (upsert path).
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from telegram_llm_bot.config.prompts import (
    PROCESSING_RESUME,
    REGISTRATION_CANCELLED,
    REGISTRATION_PROMPT,
    REGISTRATION_SAVED,
)
from telegram_llm_bot.pipeline.ingestion import ingest_resume, store_profile
from telegram_llm_bot.pipeline.parser import is_supported

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# FSM states
# ─────────────────────────────────────────────────────────────────────────────
UPLOAD_RESUME, CONFIRM_PROFILE = range(2)

# Context keys for storing intermediate state
_CTX_PROFILE = "reg_profile"
_CTX_PROFILE_DICT = "reg_profile_dict"
_CTX_VECTOR = "reg_vector"
_CTX_FILE_BYTES = "reg_file_bytes"
_CTX_FILENAME = "reg_filename"


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — /register entry point
# ─────────────────────────────────────────────────────────────────────────────

async def start_registration(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Entry point: prompt user to upload their resume."""
    await update.message.reply_text(REGISTRATION_PROMPT, parse_mode=ParseMode.MARKDOWN)
    return UPLOAD_RESUME


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — receive file
# ─────────────────────────────────────────────────────────────────────────────

async def handle_resume_upload(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive the document, run the ingestion pipeline, show preview."""
    doc = update.message.document

    if not doc:
        await update.message.reply_text(
            "⚠️ Please send a file (PDF, DOC, or DOCX), not a message.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return UPLOAD_RESUME

    filename = doc.file_name or "resume"
    mime_type = doc.mime_type

    if not is_supported(filename, mime_type):
        await update.message.reply_text(
            "❌ Unsupported file format. Please upload a *PDF*, *DOC*, or *DOCX* file.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return UPLOAD_RESUME

    # Acknowledge and show typing indicator
    processing_msg = await update.message.reply_text(
        PROCESSING_RESUME, parse_mode=ParseMode.MARKDOWN
    )

    try:
        # Download file bytes from Telegram
        tg_file = await context.bot.get_file(doc.file_id)
        import io
        buf = io.BytesIO()
        await tg_file.download_to_memory(buf)
        file_bytes = buf.getvalue()

        user = update.effective_user
        result = await ingest_resume(
            file_bytes=file_bytes,
            filename=filename,
            mime_type=mime_type,
            telegram_id=user.id,
            telegram_username=user.username,
        )

        # Store intermediate results in context for the confirmation step
        context.user_data[_CTX_PROFILE] = result.profile
        context.user_data[_CTX_PROFILE_DICT] = result.profile_dict
        context.user_data[_CTX_VECTOR] = result.vector
        context.user_data[_CTX_FILE_BYTES] = result.file_bytes
        context.user_data[_CTX_FILENAME] = result.filename

        # Show extracted preview
        preview_text = (
            "✅ *Here's what I extracted from your resume:*\n\n"
            + result.profile.format_preview()
            + "\n\n---\nDoes this look correct? Reply *yes* to save, or *no* to re-upload."
        )
        await processing_msg.edit_text(preview_text, parse_mode=ParseMode.MARKDOWN)
        return CONFIRM_PROFILE

    except ValueError as exc:
        logger.warning("Resume parse error for telegram_id=%d: %s", update.effective_user.id, exc)
        await processing_msg.edit_text(
            f"❌ {exc}\n\nPlease try a different file.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return UPLOAD_RESUME

    except Exception as exc:
        logger.exception(
            "Unexpected error during resume ingestion for telegram_id=%d",
            update.effective_user.id,
        )
        await processing_msg.edit_text(
            "⚠️ Something went wrong while processing your resume. Please try again later.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END


# ─────────────────────────────────────────────────────────────────────────────
# Step 3a — user confirms ("yes")
# ─────────────────────────────────────────────────────────────────────────────

async def confirm_profile(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """User confirmed the profile — persist to all stores."""
    user = update.effective_user

    try:
        await store_profile(
            profile=context.user_data[_CTX_PROFILE],
            profile_dict=context.user_data[_CTX_PROFILE_DICT],
            vector=context.user_data[_CTX_VECTOR],
            file_bytes=context.user_data[_CTX_FILE_BYTES],
            filename=context.user_data[_CTX_FILENAME],
            telegram_id=user.id,
            telegram_username=user.username,
        )

        _clear_context(context)
        await update.message.reply_text(REGISTRATION_SAVED, parse_mode=ParseMode.MARKDOWN)
        logger.info("Registration saved: telegram_id=%d", user.id)

    except Exception:
        logger.exception("Failed to store profile for telegram_id=%d", user.id)
        await update.message.reply_text(
            "⚠️ Failed to save your profile. Please try again later.",
            parse_mode=ParseMode.MARKDOWN,
        )

    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────────────────────
# Step 3b — user rejects ("no")
# ─────────────────────────────────────────────────────────────────────────────

async def reject_profile(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """User rejected the extracted profile — ask to re-upload."""
    _clear_context(context)
    await update.message.reply_text(
        "No problem! Please send a different file.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return UPLOAD_RESUME


# ─────────────────────────────────────────────────────────────────────────────
# Fallback — /cancel inside the conversation
# ─────────────────────────────────────────────────────────────────────────────

async def cancel_registration(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    _clear_context(context)
    await update.message.reply_text(
        REGISTRATION_CANCELLED, parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END


def _clear_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (_CTX_PROFILE, _CTX_PROFILE_DICT, _CTX_VECTOR, _CTX_FILE_BYTES, _CTX_FILENAME):
        context.user_data.pop(key, None)


# ─────────────────────────────────────────────────────────────────────────────
# ConversationHandler factory — import this in main.py
# ─────────────────────────────────────────────────────────────────────────────

def build_registration_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("register", start_registration)],
        states={
            UPLOAD_RESUME: [
                MessageHandler(filters.Document.ALL, handle_resume_upload),
            ],
            CONFIRM_PROFILE: [
                MessageHandler(filters.Regex(r"(?i)^yes$"), confirm_profile),
                MessageHandler(filters.Regex(r"(?i)^no$"), reject_profile),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_registration),
        ],
        allow_reentry=True,      # allow /register to restart mid-flow
        name="registration",
    )
