"""
config/i18n.py — user-facing bot strings in all supported languages.

LLM prompts (EXTRACTION_SYSTEM_PROMPT, MATCHMAKING_SYSTEM_PROMPT) live in
prompts.py and stay in English — models perform better that way.

Usage:
    from telegram_llm_bot.config.i18n import t
    text = t("start", lang, bot_name="DriveSynergyBot")
"""
from __future__ import annotations

from telegram import BotCommand

SUPPORTED_LANGS: list[str] = ["en", "ru"]
DEFAULT_LANG = "en"

# Per-language command menu descriptions (used with BotCommandScopeChat)
COMMANDS: dict[str, list[BotCommand]] = {
    "en": [
        BotCommand("start",    "Welcome & instructions"),
        BotCommand("register", "Submit or update your resume"),
        BotCommand("find",     "Search for community members"),
        BotCommand("mystatus", "View your current profile"),
        BotCommand("delete",   "Remove your profile"),
        BotCommand("cancel",   "Cancel current operation"),
        BotCommand("summary",  "Community overview & member count"),
        BotCommand("language", "Change language (en, ru)"),
        BotCommand("help",     "Show available commands"),
    ],
    "ru": [
        BotCommand("start",    "Приветствие и инструкции"),
        BotCommand("register", "Загрузить или обновить резюме"),
        BotCommand("find",     "Поиск участников сообщества"),
        BotCommand("mystatus", "Просмотреть текущий профиль"),
        BotCommand("delete",   "Удалить свой профиль"),
        BotCommand("cancel",   "Отменить текущую операцию"),
        BotCommand("summary",  "Обзор сообщества и число участников"),
        BotCommand("language", "Изменить язык (en, ru)"),
        BotCommand("help",     "Показать список команд"),
    ],
}

_STRINGS: dict[str, dict[str, str]] = {
    # ── /start ────────────────────────────────────────────────────────────────
    "start": {
        "en": (
            "👋 Welcome to *{bot_name}*!\n\n"
            "I help members of this community find potential partners, "
            "collaborators, and like-minded people.\n\n"
            "*What you can do:*\n"
            "• /register — upload your resume to join the network\n"
            "• /find <query> — search for people matching your needs\n"
            "• /mystatus — view your current profile\n"
            "• /help — see all commands\n\n"
            "To get started, send /register and upload your CV (PDF, DOC, or DOCX)."
        ),
        "ru": (
            "👋 Добро пожаловать в *{bot_name}*!\n\n"
            "Я помогаю участникам этого сообщества находить партнёров, "
            "соратников и единомышленников.\n\n"
            "*Что вы можете сделать:*\n"
            "• /register — загрузить резюме и вступить в сеть\n"
            "• /find <запрос> — найти подходящих участников\n"
            "• /mystatus — просмотреть свой профиль\n"
            "• /help — список всех команд\n\n"
            "Для начала отправьте /register и загрузите ваше CV (PDF, DOC или DOCX)."
        ),
    },

    # ── /help ─────────────────────────────────────────────────────────────────
    "help": {
        "en": (
            "*{bot_name} — Commands*\n\n"
            "/register — Submit or update your resume (PDF / DOC / DOCX)\n"
            "/find <query> — Search for matching community members\n"
            "/mystatus — View your current profile summary\n"
            "/delete — Remove your profile from the database\n"
            "/cancel — Cancel the current operation\n"
            "/language <code> — Change language (en, ru)\n"
            "/help — Show this help message"
        ),
        "ru": (
            "*{bot_name} — Команды*\n\n"
            "/register — Загрузить или обновить резюме (PDF / DOC / DOCX)\n"
            "/find <запрос> — Поиск участников сообщества\n"
            "/mystatus — Просмотреть текущий профиль\n"
            "/delete — Удалить свой профиль из базы\n"
            "/cancel — Отменить текущую операцию\n"
            "/language <код> — Изменить язык (en, ru)\n"
            "/help — Показать это сообщение"
        ),
    },

    # ── /mystatus ─────────────────────────────────────────────────────────────
    "mystatus_active": {
        "en": (
            "✅ *Your profile is active*\n\n"
            "👤 *Name:* {full_name}\n"
            "🔗 *Username:* {username}\n"
            "📅 *Registered:* {registered}\n"
            "🔄 *Last updated:* {updated}\n\n"
            "Use /register to update your resume, or /delete to remove your profile."
        ),
        "ru": (
            "✅ *Ваш профиль активен*\n\n"
            "👤 *Имя:* {full_name}\n"
            "🔗 *Username:* {username}\n"
            "📅 *Регистрация:* {registered}\n"
            "🔄 *Последнее обновление:* {updated}\n\n"
            "Используйте /register для обновления резюме или /delete для удаления профиля."
        ),
    },

    # ── /delete ───────────────────────────────────────────────────────────────
    "profile_deleted": {
        "en": "🗑 Your profile has been removed from the database.",
        "ru": "🗑 Ваш профиль удалён из базы данных.",
    },

    # ── /cancel ───────────────────────────────────────────────────────────────
    "cancelled": {
        "en": "❌ Operation cancelled.",
        "ru": "❌ Операция отменена.",
    },

    # ── No profile ────────────────────────────────────────────────────────────
    "no_profile": {
        "en": (
            "You don't have a profile yet. "
            "Send /register and upload your resume to join the network."
        ),
        "ru": (
            "У вас ещё нет профиля. "
            "Отправьте /register и загрузите резюме, чтобы вступить в сеть."
        ),
    },

    # ── Registration ──────────────────────────────────────────────────────────
    "registration_prompt": {
        "en": (
            "📄 Please send your resume as a *PDF*, *DOC*, or *DOCX* file.\n\n"
            "I'll extract your profile information and show you a preview before saving."
        ),
        "ru": (
            "📄 Пожалуйста, отправьте резюме в формате *PDF*, *DOC* или *DOCX*.\n\n"
            "Я извлеку информацию о вашем профиле и покажу предварительный просмотр перед сохранением."
        ),
    },
    "registration_saved": {
        "en": (
            "🎉 You're registered! Other members can now find you.\n\n"
            "Use /find to search for collaborators, or /mystatus to review your profile."
        ),
        "ru": (
            "🎉 Вы зарегистрированы! Другие участники теперь могут вас найти.\n\n"
            "Используйте /find для поиска партнёров или /mystatus для просмотра профиля."
        ),
    },
    "registration_cancelled": {
        "en": "❌ Registration cancelled. Send /register any time to try again.",
        "ru": "❌ Регистрация отменена. Отправьте /register в любое время, чтобы попробовать снова.",
    },
    "processing_resume": {
        "en": "⏳ Processing your resume, please wait...",
        "ru": "⏳ Обрабатываю резюме, подождите...",
    },

    # ── Search ────────────────────────────────────────────────────────────────
    "find_prompt": {
        "en": (
            "🔍 What are you looking for?\n\n"
            "Describe the person or skills you need, for example:\n"
            "_frontend developer with React, open to equity projects_"
        ),
        "ru": (
            "🔍 Кого вы ищете?\n\n"
            "Опишите нужного человека или навыки, например:\n"
            "_фронтенд-разработчик на React, готов к equity-проектам_"
        ),
    },
    "search_thinking": {
        "en": "🔍 Searching the community for matches...",
        "ru": "🔍 Ищу совпадения в сообществе...",
    },
    "search_results_header": {
        "en": "🔎 Found *{count}* match{plural}:\n\n",
        "ru": "🔎 Найдено *{count}* совпадени{plural}:\n\n",
    },
    "match_card_why": {
        "en": "🤝 *Why:*",
        "ru": "🤝 *Почему подходит:*",
    },
    "match_card_skills": {
        "en": "🛠 *Skills:*",
        "ru": "🛠 *Навыки:*",
    },
    "match_card_contact": {
        "en": "Contact",
        "ru": "Написать",
    },
    "search_no_results": {
        "en": (
            "😕 No matching profiles found for your query.\n\n"
            'Try rephrasing — for example: "frontend developer with React, open to equity projects"'
        ),
        "ru": (
            "😕 По вашему запросу ничего не найдено.\n\n"
            "Попробуйте переформулировать — например: «фронтенд-разработчик на React, готов к equity-проектам»"
        ),
    },

    # ── /summary ─────────────────────────────────────────────────────────────
    "summary_thinking": {
        "en": "📊 Analysing the community, please wait...",
        "ru": "📊 Анализирую сообщество, подождите...",
    },
    "summary_header": {
        "en": "👥 *Community Summary*\n\n👤 *Registered members:* {count}\n\n",
        "ru": "👥 *Обзор сообщества*\n\n👤 *Зарегистрировано участников:* {count}\n\n",
    },
    "summary_error": {
        "en": "⚠️ Could not generate the summary. Please try again later.",
        "ru": "⚠️ Не удалось сформировать обзор. Попробуйте позже.",
    },
    "summary_empty": {
        "en": "😕 No members registered yet.",
        "ru": "😕 Пока нет зарегистрированных участников.",
    },

    # ── Fallback ──────────────────────────────────────────────────────────────
    "unknown_message": {
        "en": (
            "I didn't understand that. Please use one of the available commands.\n\n"
            "Tap the */* button or type /help to see what I can do."
        ),
        "ru": (
            "Я не понял это сообщение. Пожалуйста, используйте одну из доступных команд.\n\n"
            "Нажмите кнопку */* или введите /help, чтобы увидеть список команд."
        ),
    },

    # ── /language ─────────────────────────────────────────────────────────────
    "language_changed": {
        "en": "✅ Language set to *English*.",
        "ru": "✅ Язык изменён на *русский*.",
    },
    "language_unknown": {
        "en": "❓ Unknown language code. Supported languages: *en*, *ru*.\nExample: `/language ru`",
        "ru": "❓ Неизвестный код языка. Поддерживаемые языки: *en*, *ru*.\nПример: `/language en`",
    },
    "language_usage": {
        "en": "ℹ️ Usage: `/language <code>`\nSupported codes: *en*, *ru*",
        "ru": "ℹ️ Использование: `/language <код>`\nДоступные коды: *en*, *ru*",
    },
}


def t(key: str, lang: str, **kwargs: object) -> str:
    """
    Return the translated string for *key* in *lang*.

    Falls back to English if *lang* is not supported or the key is missing.
    Any **kwargs are forwarded to str.format().
    """
    lang = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    translations = _STRINGS.get(key, {})
    text = translations.get(lang) or translations.get(DEFAULT_LANG, f"[missing: {key}]")
    return text.format(**kwargs) if kwargs else text
