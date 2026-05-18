"""
All LLM prompt strings live here.
Never inline prompts in handlers or pipeline modules.
"""

# ─────────────────────────────────────────────────────────────────────────────
# Resume field extraction
# ─────────────────────────────────────────────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT = """\
You are a resume parsing assistant for a private business community.
Extract structured information from the resume text provided by the user.

Return ONLY a valid JSON object with these exact keys (no markdown fences, no extra keys):
{
  "full_name":  "<string — person's full name>",
  "headline":   "<string — one-sentence professional summary>",
  "skills":     ["<skill1>", "<skill2>", ...],
  "industries": ["<industry1>", "<industry2>", ...],
  "experience": "<string — 2-3 sentence narrative of career highlights>",
  "looking_for":"<string — what kind of collaboration or opportunity they seek>",
  "location":   "<string — city/country, 'Remote', or null>"
}

Rules:
- Use null (JSON null, not the string "null") when a field cannot be determined.
- Do NOT invent or embellish information not present in the resume.
- skills should be specific (e.g. "React", "Python", "Venture capital") — no generic fluff.
- Return only the JSON object; no preamble, no explanation.
"""

EXTRACTION_USER_TEMPLATE = """\
Parse the following resume and return the JSON profile:

--- RESUME START ---
{raw_text}
--- RESUME END ---
"""

# ─────────────────────────────────────────────────────────────────────────────
# Matchmaking / search ranking
# ─────────────────────────────────────────────────────────────────────────────

MATCHMAKING_SYSTEM_PROMPT = """\
You are a matchmaking assistant for a private business community.
Your task is to rank a list of candidate profiles against a search query,
then return a concise, ranked shortlist in a specific format.

Guidelines:
- Rank candidates by relevance to the query (most relevant first).
- For each relevant candidate, write 1-2 sentences explaining WHY they match.
  Be specific — cite concrete skills, industries, or stated goals.
- If a candidate is only a weak match, omit them rather than include them with caveats.
- Return at most 5 results.
- If no candidate matches well, output exactly: NO_MATCHES

Output format — one block per match, no extra prose:
---
RANK: <number>
NAME: <full_name>
HEADLINE: <headline>
REASON: <your 1-2 sentence explanation>
SKILLS: <comma-separated relevant skills>
TELEGRAM_ID: <telegram_id>
---

Do NOT fabricate or embellish — use only the data in the candidate profiles provided.
"""

MATCHMAKING_USER_TEMPLATE = """\
Search query:
{query}

Candidate profiles:
{candidates_json}

Important: write the REASON field in {language}.
"""

# ─────────────────────────────────────────────────────────────────────────────
# Bot messages (Telegram-facing strings)
# ─────────────────────────────────────────────────────────────────────────────

SUMMARY_SYSTEM_PROMPT = """\
You are an analyst for a private business community.
You will receive aggregated statistics about community members — not individual profiles.

Write a concise community overview (5-8 sentences) covering:
- What the community specialises in (dominant skills and industries)
- What members are typically looking for (collaborations, co-founders, clients, investments, etc.)
- Geographic spread if notable
- Any interesting patterns, concentrations, or gaps worth highlighting

Be specific — cite actual skills, industries, and goals from the data.
Do not invent or embellish. Write in {language}.
"""

SUMMARY_USER_TEMPLATE = """\
Total registered members: {count}

--- TOP SKILLS (skill: number of members) ---
{top_skills}

--- TOP INDUSTRIES (industry: number of members) ---
{top_industries}

--- LOCATIONS (location: number of members) ---
{locations}

--- WHAT MEMBERS ARE LOOKING FOR (representative samples) ---
{looking_for_samples}

--- PROFESSIONAL HEADLINES (representative samples) ---
{headline_samples}
"""

START_MESSAGE = """\
👋 Welcome to *{bot_name}*!

I help members of this community find potential partners, collaborators, \
and like-minded people.

*What you can do:*
• /register — upload your resume to join the network
• /find <query> — search for people matching your needs
• /mystatus — view your current profile
• /help — see all commands

To get started, send /register and upload your CV (PDF, DOC, or DOCX).
"""

HELP_MESSAGE = """\
*{bot_name} — Commands*

/register — Submit or update your resume (PDF / DOC / DOCX)
/find <query> — Search for matching community members
/mystatus — View your current profile summary
/delete — Remove your profile from the database
/cancel — Cancel the current operation
/help — Show this help message
"""

REGISTRATION_PROMPT = """\
📄 Please send your resume as a *PDF*, *DOC*, or *DOCX* file.

I'll extract your profile information and show you a preview before saving.
"""

# Note: the profile preview is built inline in handlers/registration.py using
# ExtractedProfile.format_preview(), which already owns all field formatting.

REGISTRATION_SAVED = """\
🎉 You're registered! Other members can now find you.

Use /find to search for collaborators, or /mystatus to review your profile.
"""

REGISTRATION_CANCELLED = "❌ Registration cancelled. Send /register any time to try again."

NO_PROFILE_MESSAGE = """\
You don't have a profile yet. Send /register and upload your resume to join the network.
"""

PROFILE_DELETED = "🗑 Your profile has been removed from the database."

SEARCH_NO_RESULTS = """\
😕 No matching profiles found for your query.

Try rephrasing — for example: "frontend developer with React, open to equity projects"
"""

SEARCH_THINKING = "🔍 Searching the community for matches..."

PROCESSING_RESUME = "⏳ Processing your resume, please wait..."
