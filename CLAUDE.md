# CLAUDE.md — Resume Matchmaking Telegram Bot

This file is the primary context document for AI-assisted development of this project.
Read it fully before writing any code or making any changes.

---

## Project Goal

Build a resume matchmaking bot for a private Telegram business community.

Community members can:
1. **Register** — submit a structured resume by uploading a PDF/DOCX file through a guided
   conversation flow
2. **Update** — re-upload a file to replace their existing profile
3. **Search** — send a natural language query and receive a ranked list of matched profiles,
   each with a Telegram contact link and a resume download link

The bot lives in a **group chat** and also responds in **private chat**.
It is not a public product — it serves a known, closed community.

---

## Base Repository

**Source:** `https://github.com/ma2za/telegram-llm-bot`

Clone and fork this repo. Do not start from scratch.

### What is reused as-is (~40%)
- `compose.yaml` — Docker Compose wiring for all services
- MongoDB container + client setup
- Weaviate container
- MinIO container
- LangChain scaffolding and imports
- `logging.conf`
- `pyproject.toml` / `poetry.lock` (extend, don't replace)

### What requires heavy modification
- `src/telegram_llm_bot/bots/base_chatbot/settings.py` — replace Beam/LLaMA settings
  with Anthropic API settings and matchmaking-specific config
- All `.env` files — replace with the env vars listed in this document
- `compose.yaml` — remove Beam-related services, keep MongoDB/Weaviate/MinIO

### What must be built from scratch
- FSM-based registration `ConversationHandler`
- Resume ingestion pipeline (parse → extract structured fields → embed → store)
- Weaviate schema for member profiles
- Semantic search + matchmaking handler
- Re-upload / profile update logic
- Admin access control (allowlist by Telegram user ID)
- `/help`, `/mystatus`, `/delete` commands

---

## Tech Stack

| Layer | Library / Service |
|---|---|
| Bot framework | `python-telegram-bot` v20+ (async) |
| LLM | Anthropic Claude via `anthropic` SDK (not LangChain's Anthropic wrapper unless needed) |
| LLM orchestration | LangChain LCEL where useful; direct API calls preferred for simplicity |
| Vector database | Weaviate (self-hosted via Docker, already in compose.yaml) |
| Object storage | MinIO (self-hosted via Docker, stores original resume files) |
| Database | MongoDB (stores user registry: telegram_id → profile metadata) |
| Resume parsing | `pymupdf` (fitz) for PDFs; `python-docx` for DOCX |
| Embeddings | `text-embedding-3-small` via OpenAI, or `all-MiniLM-L6-v2` via sentence-transformers |
| Infrastructure | Docker Compose |

---

## Repository Structure (target state after build)

```
telegram-llm-bot/
├── compose.yaml                        # Docker Compose — all services
├── pyproject.toml
├── logging.conf
├── .env                                # Root env (MongoDB, Weaviate, MinIO credentials)
├── CLAUDE.md                           # This file
│
└── src/
    └── telegram_llm_bot/
        ├── __init__.py
        ├── main.py                     # Entry point — builds and runs the Application
        │
        ├── config/
        │   ├── settings.py             # Pydantic Settings — loads all env vars
        │   └── prompts.py              # All system prompts and prompt templates
        │
        ├── handlers/
        │   ├── registration.py         # ConversationHandler FSM for /register
        │   ├── search.py               # /find and free-text query handler
        │   ├── commands.py             # /start /help /mystatus /delete /cancel
        │   └── admin.py                # Admin-only commands (/stats, /list_users)
        │
        ├── pipeline/
        │   ├── parser.py               # PDF/DOCX → raw text extraction
        │   ├── extractor.py            # LLM call to extract structured fields from text
        │   ├── embedder.py             # text → vector via embedding model
        │   └── ingestion.py            # Orchestrates parser → extractor → embedder → store
        │
        ├── storage/
        │   ├── weaviate_client.py      # Weaviate connection, schema creation, upsert, search
        │   ├── mongo_client.py         # MongoDB connection, user registry CRUD
        │   └── minio_client.py         # MinIO connection, resume file upload/download
        │
        └── matching/
            └── agent.py                # Matchmaking LLM agent — takes query, returns ranked list
```

---

## Environment Variables

All env vars are loaded via `config/settings.py` using `pydantic-settings`.
Never hardcode credentials.

**Root `.env` (infrastructure):**
```
MONGODB_URI=mongodb://mongo:27017
MONGODB_DB=matchbot

WEAVIATE_HOST=weaviate
WEAVIATE_PORT=8080

MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=resumes
```

**Bot `.env` (`src/telegram_llm_bot/.env`):**
```
TELEGRAM_BOT_TOKEN=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=                         # Only needed if using OpenAI embeddings

ADMIN_TELEGRAM_IDS=123456789,987654321  # Comma-separated list of admin user IDs
ALLOWED_GROUP_ID=                        # Telegram group chat ID where bot is active

BOT_NAME=MatchBot
MATCHMAKING_SYSTEM_PROMPT_FILE=src/telegram_llm_bot/config/prompts.py
```

---

## Data Models

### MongoDB — `users` collection

```python
{
    "telegram_id": int,           # Telegram user ID (primary key)
    "telegram_username": str,     # @handle, may be None
    "full_name": str,             # Extracted from resume or provided during registration
    "registered_at": datetime,
    "updated_at": datetime,
    "profile_status": str,        # "active" | "deleted"
    "minio_key": str,             # Path to original resume file in MinIO
    "weaviate_uuid": str,         # UUID of the profile object in Weaviate
}
```

### Weaviate — `MemberProfile` class

```python
{
    "class": "MemberProfile",
    "properties": [
        {"name": "telegram_id",    "dataType": ["int"]},
        {"name": "full_name",      "dataType": ["text"]},
        {"name": "headline",       "dataType": ["text"]},   # 1-sentence summary
        {"name": "skills",         "dataType": ["text[]"]}, # list of skill tags
        {"name": "industries",     "dataType": ["text[]"]},
        {"name": "experience",     "dataType": ["text"]},   # narrative paragraph
        {"name": "looking_for",    "dataType": ["text"]},   # what they want
        {"name": "location",       "dataType": ["text"]},
        {"name": "resume_text",    "dataType": ["text"]},   # full extracted text for RAG
    ],
    "vectorizer": "none",          # we provide our own vectors
}
```

The vector stored per object is the embedding of:
`f"{headline}\n{skills_joined}\n{experience}\n{looking_for}"`

---

## Registration Flow (FSM)

Implemented as a `ConversationHandler` in `handlers/registration.py`.

```
/register
    │
    ├── STATE_UPLOAD_RESUME
    │       Bot: "Please send your resume as a PDF or DOCX file."
    │       User: sends file
    │           → pipeline/ingestion.py runs (parse → extract → preview)
    │
    ├── STATE_CONFIRM_PROFILE
    │       Bot: shows extracted profile fields for review
    │       User: "yes" → proceed | "no" → re-upload
    │
    └── STATE_DONE
            Bot: stores to Weaviate + MongoDB + MinIO
            Bot: "You're registered! Other members can now find you."
```

States are integer constants defined at module top. Use `ConversationHandler.END` to exit.

**Re-upload:** `/register` on an existing user triggers the same flow but performs
an **upsert** — the old Weaviate object is deleted by UUID and replaced, MinIO file
is overwritten, MongoDB `updated_at` is set.

---

## Resume Ingestion Pipeline

Located in `pipeline/`. Each step is a pure function or simple class.

### Step 1 — `parser.py`

```python
def extract_text(file_bytes: bytes, mime_type: str) -> str:
    """Returns raw text from PDF or DOCX bytes."""
```

Use `fitz.open(stream=file_bytes)` for PDFs.
Use `python-docx` `Document(BytesIO(file_bytes))` for DOCX.
Strip excessive whitespace. Return plain string.

### Step 2 — `extractor.py`

Single LLM call to Claude to extract structured fields.
Use `anthropic` SDK directly (not LangChain) for this step.

```python
def extract_profile_fields(raw_text: str) -> dict:
    """
    Calls Claude to extract structured profile from raw resume text.
    Returns dict matching Weaviate MemberProfile properties.
    """
```

The extraction prompt is in `config/prompts.py` (see Prompts section below).
Parse the response as JSON. Validate with Pydantic before returning.

### Step 3 — `embedder.py`

```python
def embed_profile(profile: dict) -> list[float]:
    """Creates embedding vector for the profile."""
```

Concatenate `headline + skills + experience + looking_for` into a single string.
Embed with `text-embedding-3-small` (1536 dims) or `all-MiniLM-L6-v2` (384 dims).
Keep the model choice in `settings.py` so it can be swapped.

### Step 4 — `ingestion.py`

Orchestrates steps 1–3 and writes to all three storage layers.
Called by the registration handler after user confirmation.

---

## Matchmaking Agent

Located in `matching/agent.py`.

User sends a free-text query like:
> "Looking for a frontend developer with React experience who is open to equity-based projects"

Flow:
1. Embed the query using the same embedding model as profiles
2. Run Weaviate hybrid search (vector + BM25 keyword) against `MemberProfile`
3. Retrieve top 5–10 candidates with their profile fields
4. Call Claude with the matchmaking system prompt, the query, and candidate summaries
5. Claude returns a ranked shortlist with reasoning per candidate
6. Format for Telegram: each result is a card with name, headline, skills, and a
   `tg://user?id={telegram_id}` deep link + `/resume_{telegram_id}` download command

**Search command:** `/find <query>` — also handles free-text messages in group chat
if the message starts with a mention of the bot.

---

## Prompts (`config/prompts.py`)

### Profile Extraction Prompt

```python
EXTRACTION_SYSTEM_PROMPT = """
You are a resume parsing assistant. Extract structured information from the resume text below.
Return ONLY a valid JSON object with these exact keys:
- full_name (string)
- headline (string, 1 sentence professional summary)
- skills (array of strings, specific technical or domain skills)
- industries (array of strings, industries the person has worked in)
- experience (string, 2-3 sentence narrative of career highlights)
- looking_for (string, what kind of collaboration or opportunity they seek)
- location (string, city/country or "Remote", null if not mentioned)

If a field cannot be determined from the resume, use null.
Do not invent information. Do not include markdown formatting in the JSON.
"""
```

### Matchmaking System Prompt

```python
MATCHMAKING_SYSTEM_PROMPT = """
You are a matchmaking assistant for a private business community.
Your job is to find the best matches from a database of member profiles
for a given search query.

You will receive:
1. A search query from a community member
2. A list of candidate profiles retrieved from the database

Your task:
- Rank the candidates by relevance to the query
- For each relevant candidate, explain in 1-2 sentences WHY they are a match
- Be specific — mention concrete skills, industries, or goals that align
- If a candidate is only a weak match, say so honestly or omit them
- Return at most 5 results
- If no candidates match well, say so clearly

Output format — for each match:
**{full_name}** — {headline}
Match reason: {your explanation}
Skills: {relevant skills}
[Contact] [View Resume]

Do not fabricate or embellish profile information.
Only use what is provided in the candidate data.
"""
```

---

## Bot Commands

| Command | Description | Access |
|---|---|---|
| `/start` | Welcome message and instructions | All |
| `/register` | Start registration / re-upload flow | All |
| `/find <query>` | Search for matching profiles | Registered members |
| `/mystatus` | Show your current profile summary | All |
| `/delete` | Remove your profile from the database | Registered members |
| `/cancel` | Cancel current conversation flow | All |
| `/help` | Show available commands | All |
| `/stats` | Show total member count | Admin only |
| `/list` | List all registered members | Admin only |

---

## Access Control

- The bot accepts commands from:
  - Any private chat with a registered member
  - The group chat defined in `ALLOWED_GROUP_ID`
- Admin commands check `update.effective_user.id in settings.admin_telegram_ids`
- `/find` requires the user to be registered (check MongoDB before proceeding)
- Unknown users get a friendly message directing them to `/register`

---

## Docker Compose Services

The `compose.yaml` should run these services:

```
bot         — the Python bot application
mongodb     — MongoDB 6.x
weaviate    — Weaviate v1.x
minio       — MinIO object storage
```

Remove or comment out Beam-related services from the original repo.
The bot service should have `depends_on: [mongodb, weaviate, minio]` with health checks.

---

## Development Conventions

- Python 3.11+
- Async throughout — all handlers are `async def`, all storage clients use async where available
- Type hints on all function signatures
- Pydantic models for all data structures crossing service boundaries
- Never store raw bytes in MongoDB — use MinIO for files, store only the MinIO key in Mongo
- Log all LLM calls (model, token count, latency) at DEBUG level
- Errors surfaced to users should be friendly; full tracebacks go to logs only
- All prompts live in `config/prompts.py` — never inline prompt strings in handlers

---

## Build Order (recommended sequence for AI-assisted development)

**Phase 1 — Infrastructure (do first, verify before moving on)**
1. Clean up `compose.yaml` — remove Beam, verify MongoDB/Weaviate/MinIO start cleanly
2. Write `config/settings.py` with Pydantic Settings
3. Write `storage/mongo_client.py` — connect, create index on `telegram_id`
4. Write `storage/weaviate_client.py` — connect, create `MemberProfile` schema
5. Write `storage/minio_client.py` — connect, create bucket

**Phase 2 — Ingestion Pipeline**
6. Write `pipeline/parser.py` — PDF and DOCX extraction
7. Write `pipeline/extractor.py` — LLM structured extraction
8. Write `pipeline/embedder.py` — embedding generation
9. Write `pipeline/ingestion.py` — orchestrate 6–8, write to all stores

**Phase 3 — Bot Handlers**
10. Write `handlers/commands.py` — `/start`, `/help`, `/cancel`, `/mystatus`
11. Write `handlers/registration.py` — full FSM ConversationHandler
12. Wire `main.py` — build Application, attach all handlers

**Phase 4 — Search & Matching**
13. Implement hybrid search in `storage/weaviate_client.py`
14. Write `matching/agent.py` — embed query → retrieve → LLM rank → format
15. Write `handlers/search.py` — `/find` command + free-text trigger

**Phase 5 — Polish**
16. Write `handlers/admin.py`
17. Add re-upload logic (upsert path) in `handlers/registration.py`
18. Add `/delete` command
19. End-to-end test with real Telegram bot token

---

## Key References

- python-telegram-bot docs: https://docs.python-telegram-bot.org
- ConversationHandler guide: https://docs.python-telegram-bot.org/en/stable/conversationhandler.html
- Weaviate Python client v4: https://weaviate.io/developers/weaviate/client-libraries/python
- Weaviate hybrid search: https://weaviate.io/developers/weaviate/search/hybrid
- Anthropic SDK: https://docs.anthropic.com/en/api/getting-started
- MinIO Python SDK: https://min.io/docs/minio/linux/developers/python/API.html
