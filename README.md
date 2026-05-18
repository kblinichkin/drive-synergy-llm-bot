# DriveSynergyBot

A resume matchmaking Telegram bot for private business communities. Members upload their CV, the bot extracts a structured profile, and anyone can search for collaborators, co-founders, or specialists using natural language queries.

---

## Features

| Command | Description |
|---|---|
| `/start` | Welcome message and instructions |
| `/register` | Upload a resume (PDF / DOC / DOCX) to join the network |
| `/find` | Search for matching community members |
| `/mystatus` | View your current profile |
| `/summary` | Community overview — member count + LLM-generated analysis |
| `/delete` | Remove your profile |
| `/language` | Switch bot language (🇬🇧 English / 🇷🇺 Русский) |
| `/help` | List all commands |
| `/stats` | Total member count *(admin only)* |
| `/list` | List all registered members *(admin only)* |

**Languages:** English and Russian, auto-detected from Telegram locale and overridable per-user.

---

## How it works

```
User uploads PDF/DOCX
        │
        ▼
   parser.py          — extract raw text (pymupdf / python-docx)
        │
        ▼
   extractor.py       — LLM call → structured JSON (name, headline,
        │               skills, industries, experience, looking_for, location)
        ▼
   embedder.py        — sentence-transformers → 384-dim vector
        │
        ├──▶ Weaviate  — profile + vector (for semantic search)
        ├──▶ MongoDB   — user registry (telegram_id, status, timestamps)
        └──▶ MinIO     — original resume file
```

**Search flow:**

```
User types query
        │
        ▼
   embed query        — same model as profiles
        │
        ▼
   Weaviate hybrid    — vector + BM25 keyword search → top 10 candidates
        │
        ▼
   LLM re-rank        — ranks candidates, writes match reasons
        │
        ▼
   Result cards       — name, headline, match reason, skills, contact link
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Bot framework | python-telegram-bot v21 (async) |
| LLM | OpenRouter (configurable model, e.g. `anthropic/claude-3-haiku`) |
| Embeddings | `all-MiniLM-L6-v2` via sentence-transformers (local, no API key) |
| Vector database | Weaviate 1.27+ (self-hosted) |
| Object storage | MinIO (self-hosted, stores original resume files) |
| Database | MongoDB 6 (user registry) |
| Resume parsing | pymupdf (PDF), python-docx (DOCX), antiword (legacy .doc) |
| Infrastructure | Docker Compose |

---

## Prerequisites

- Docker + Docker Compose (Docker Desktop or OrbStack on macOS)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- An [OpenRouter](https://openrouter.ai) API key

---

## Configuration

All settings are loaded from environment variables via `config/settings.py`. Never commit credential files.

### `.env` — infrastructure

```
MONGODB_URI=mongodb://mongo:27017
MONGODB_DB=matchbot
```

### `.env.bot` — bot credentials

```
TELEGRAM_BOT_TOKEN=          # from @BotFather
OPENROUTER_API_KEY=          # from openrouter.ai
OPENROUTER_MODEL=anthropic/claude-3-haiku   # any OpenRouter model slug

ADMIN_TELEGRAM_IDS=123456789  # comma-separated, for /stats and /list
ALLOWED_GROUP_ID=             # optional: restrict to one group chat

EMBEDDING_MODEL=all-MiniLM-L6-v2
EMBEDDING_DIMS=384

MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=resumes

SEARCH_TOP_K=10     # candidates fetched from Weaviate
SEARCH_RETURN_TOP=5 # results shown after LLM re-rank
```

---

## Running locally

### Path A — everything in Docker (recommended)

All four services (`mongo`, `weaviate`, `minio`, `matchbot`) run together, read env from `.env` + `.env.bot`, and talk to each other by service name.

```bash
# First time only — build the bot image (~3 min)
docker compose build matchbot

# Start infrastructure, wait for healthy status
docker compose up -d mongo weaviate minio
docker compose ps

# Start the bot in foreground (Ctrl+C to stop)
docker compose up matchbot
```

You should see these lines in order:

```
Starting DriveSynergyBot (model=anthropic/claude-3-haiku)...
MongoDB indexes ensured.
Weaviate schema ensured.
MinIO bucket ensured.
Bot commands registered.
MatchBot ready ✓
```

**Quick smoke test:**

1. Open a private Telegram chat with your bot.
2. Send `/start` — welcome message (tests handler dispatch, no LLM).
3. Send `/register`, upload any PDF/DOCX resume.
   You should see in the logs: `OpenRouter extraction: model=… tokens_in=… latency=…s`
4. Confirm the preview, then send `/find React developer fintech` — you should see: `OpenRouter matchmaking: model=… tokens_in=… latency=…s`

**Full rebuild and restart** (after code changes):

```bash
docker compose down
docker compose build matchbot
docker compose up -d mongo weaviate minio
docker compose up matchbot
```

**Stop and wipe data volumes:**

```bash
docker compose down -v   # removes mongo/weaviate/minio data too
```

**Inspect data while the bot runs:**

```bash
# MinIO web console
open http://localhost:9001          # login: minioadmin / minioadmin

# MongoDB shell
docker compose exec mongo mongosh matchbot
> db.users.find().pretty()

# Weaviate schema
curl http://localhost:8080/v1/schema
```

---

### Path B — bot on host, infra in Docker (better for debugging)

Useful when you want breakpoints, `pdb`, or hot-reload without rebuilding the image.

```bash
# 1. Start only infra
docker compose up -d mongo weaviate minio

# 2. Use the local env overrides (points at localhost instead of docker DNS)
cp .env.local.example .env.local

# 3. Install Python deps on the host
poetry install

# 4. Load all env files and run
set -a
source .env
source .env.bot
source .env.local   # must come last to override docker service hostnames
set +a

poetry run python -m telegram_llm_bot.main
```

The first run downloads the `all-MiniLM-L6-v2` model (~90 MB). Subsequent runs are instant.

---

### Useful debug commands

```bash
# Tail bot logs, show only LLM and error lines
docker compose logs -f matchbot | grep -E "OpenRouter|ERROR|extraction|matchmaking"

# Reset only the vector DB (keeps user registry in Mongo)
docker compose exec weaviate curl -X DELETE http://localhost:8080/v1/schema/MemberProfile

# Check bot can reach OpenRouter from inside the container
docker compose exec matchbot python -c "
import os, httpx
r = httpx.get('https://openrouter.ai/api/v1/models',
              headers={'Authorization': f\"Bearer {os.environ['OPENROUTER_API_KEY']}\"},
              timeout=10)
print(r.status_code, r.text[:200])
"
```

---

### Common gotchas

| Symptom | Cause | Fix |
|---|---|---|
| `ValidationError: openrouter_api_key Field required` | `.env.bot` not loaded | Run from project root; check `env_file` in `compose.yaml` |
| `getaddrinfo failed: 'weaviate'` | Using Path B without `.env.local` | Re-source `.env.local` |
| `Unauthorized: 401` from Telegram | Placeholder token | Fill in `TELEGRAM_BOT_TOKEN` |
| `401 Unauthorized` from OpenRouter | Invalid key | Check `OPENROUTER_API_KEY` |
| "Unsupported file format" for a valid PDF | Scanned image PDF (no selectable text) | Confirm by trying to select text in a PDF viewer |
| Weaviate unhealthy on startup | Slow first boot (~30–60 s on ARM) | `start_period: 60s` is set in `compose.yaml`; just wait |

---

## Planned features *(TBD)*

### Voice input for search queries

Instead of typing a `/find` query, users could send a voice message. The pipeline would be:

```
Voice message
      │
      ▼
OpenAI Whisper API     — speech-to-text transcription (whisper-1 model)
      │
      ▼
LLM cleanup pass       — correct ASR errors, normalise punctuation,
      │                  keep content and language unchanged
      ▼
/find pipeline         — embed → Weaviate search → LLM rank → result cards
```

**Technology stack:**
- Transcription: `openai.Audio.transcribe("whisper-1", ...)` — language auto-detected or pinned per user
- Post-processing: one short LLM call to fix ASR artefacts before the text is used as a search query (avoids nonsense embeddings from garbled speech)
- For Azure production: Azure AI Speech (Speech-to-Text) can replace Whisper; Azure OpenAI handles the cleanup pass

**Implementation notes:**
- Add a `MessageHandler(filters.VOICE, voice_search_handler)` alongside the existing `/find` ConversationHandler
- The voice handler downloads the `.oga` file, transcribes it, then feeds the result into `_run_search()` — no changes needed to the search pipeline itself
- Per-user daily transcription limits (seconds of audio) should be enforced to control API costs; MongoDB `users` collection can store the counter

---

## Production deployment on Azure *(TBD)*

> This section documents the intended Azure deployment path. Implementation is pending.

### Planned architecture

The local Docker Compose setup maps directly to managed Azure services:

| Local (Docker Compose) | Azure equivalent |
|---|---|
| `matchbot` container | Azure Container Apps |
| MongoDB | Azure Cosmos DB for MongoDB |
| Weaviate | Self-hosted on AKS, or Azure AI Search *(evaluate)* |
| MinIO | Azure Blob Storage |

### LLM provider for production

For production, the bot can be switched from OpenRouter to **Azure OpenAI** by changing three settings in `.env.bot`:

```
# Replace these OpenRouter settings…
OPENROUTER_API_KEY=…
OPENROUTER_MODEL=anthropic/claude-3-haiku
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# …with Azure OpenAI equivalents
AZURE_OPENAI_API_KEY=…
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=<your-deployment-name>
AZURE_OPENAI_API_VERSION=2024-02-01
```

The OpenAI Python SDK (already a dependency) supports Azure OpenAI natively via `AzureOpenAI` client — no extra packages needed. The switch requires a small update to `matching/agent.py` and `pipeline/extractor.py` to instantiate `AzureOpenAI` instead of the OpenRouter-pointed `AsyncOpenAI`.

### Still to be defined

- [ ] Azure Container Apps deployment YAML / Bicep templates
- [ ] Secrets management (Azure Key Vault)
- [ ] CI/CD pipeline (GitHub Actions → ACR → Container Apps)
- [ ] Cosmos DB connection string and index configuration
- [ ] Azure Blob Storage adapter (drop-in for MinIO client)
- [ ] Weaviate hosting decision (AKS vs managed alternative)
- [ ] Environment promotion strategy (dev → staging → prod)

---

## Project structure

```
src/telegram_llm_bot/
├── main.py                  # Entry point — builds Application, registers handlers
│
├── config/
│   ├── settings.py          # Pydantic Settings — all env vars
│   ├── prompts.py           # LLM system prompts and templates
│   └── i18n.py              # User-facing strings in en / ru
│
├── handlers/
│   ├── registration.py      # ConversationHandler FSM for /register
│   ├── search.py            # /find — ConversationHandler + search execution
│   ├── commands.py          # /start /help /mystatus /delete /summary /language
│   ├── admin.py             # /stats /list (admin only)
│   ├── fallback.py          # Catch-all for unrecognised messages
│   └── i18n_helpers.py      # get_lang(), sync_commands()
│
├── pipeline/
│   ├── parser.py            # PDF/DOCX → raw text
│   ├── extractor.py         # LLM → structured profile fields
│   ├── embedder.py          # text → vector
│   └── ingestion.py         # Orchestrates parser → extractor → embedder → store
│
├── storage/
│   ├── weaviate_client.py   # Schema, upsert, hybrid search, fetch_all_profiles
│   ├── mongo_client.py      # User registry CRUD, language preference
│   └── minio_client.py      # Resume file upload/download/delete
│
└── matching/
    └── agent.py             # Embed query → Weaviate search → LLM rank → format cards
```

---

## Data model

### MongoDB — `users` collection

```json
{
  "telegram_id": 123456789,
  "telegram_username": "username",
  "full_name": "Jane Smith",
  "registered_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z",
  "profile_status": "active",
  "lang": "ru",
  "minio_key": "resumes/123456789/cv.pdf",
  "weaviate_uuid": "..."
}
```

### Weaviate — `MemberProfile` collection

Fields: `telegram_id`, `full_name`, `headline`, `skills`, `industries`, `experience`, `looking_for`, `location`, `resume_text`.
Vector is the embedding of `headline + skills + experience + looking_for`.

---

## Adding a language

1. Add the language code to `SUPPORTED_LANGS` in `config/i18n.py`
2. Add translations for every key in `_STRINGS`
3. Add a `BotCommand` list entry in `COMMANDS`
4. Add a button in `_LANGUAGE_LABELS` in `handlers/commands.py`
