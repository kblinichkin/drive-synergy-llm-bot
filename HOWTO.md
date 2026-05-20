# HOWTO — Quick-reference commands

All commands run from the project root unless noted otherwise.

---

## First-time setup

```bash
# 1. Copy the env templates and fill in your credentials
cp .env.example .env          # MongoDB URI (already filled for local Docker)
cp .env.bot.example .env.bot  # Telegram token + OpenRouter key — MUST be filled

# 2. Build the bot image (~ 3 min, downloads Python deps + sentence-transformer model)
docker compose build matchbot

# 3. Start infrastructure and wait for healthy status
docker compose up -d mongo weaviate minio
docker compose ps             # all three should show "healthy" within ~60 s

# 4. Start the bot in the foreground (Ctrl+C to stop)
docker compose up matchbot
```

Expected startup lines (in order):

```
Starting DriveSynergyBot (model=anthropic/claude-3-haiku)...
MongoDB indexes ensured.
Weaviate schema ensured.
MinIO bucket ensured.
Bot commands registered.
MatchBot ready ✓
```

---

## Daily operations

```bash
# Start everything (detached)
docker compose up -d

# Stop everything (keep data volumes)
docker compose down

# View live bot logs
docker compose logs -f matchbot

# View only LLM calls and errors
docker compose logs -f matchbot | grep -E "OpenRouter|ERROR|extraction|matchmaking"
```

---

## Rebuild after code changes

```bash
docker compose down
docker compose build matchbot
docker compose up -d mongo weaviate minio
docker compose up matchbot
```

> Only `matchbot` needs rebuilding for Python code changes.
> Infrastructure images (`mongo`, `weaviate`, `minio`) never need rebuilding.

---

## Dependency changes (pyproject.toml edited)

When you add or update a Python dependency:

```bash
# Re-lock inside a temporary container (avoids needing Poetry locally)
docker compose run --rm --no-deps matchbot poetry lock

# Then rebuild the image so the new lock file is baked in
docker compose build matchbot
```

---

## Wipe and reset

```bash
# Stop containers and delete all data volumes (Mongo + Weaviate + MinIO)
docker compose down -v

# Full clean slate — remove image too
docker compose down -v --rmi local
docker compose build matchbot
docker compose up -d mongo weaviate minio
docker compose up matchbot
```

---

## Inspect data while the bot is running

```bash
# MinIO web console  →  http://localhost:9001
#   login: minioadmin / minioadmin
open http://localhost:9001

# MongoDB shell
docker compose exec mongo mongosh matchbot
> db.users.find().pretty()
> db.users.countDocuments({profile_status: "active"})

# Weaviate REST — collection schema
curl -s http://localhost:8080/v1/schema | python3 -m json.tool

# Weaviate REST — object count
curl -s "http://localhost:8080/v1/objects?class=MemberProfile&limit=1" | python3 -m json.tool

# Reset only the vector index (keeps user registry in Mongo and files in MinIO)
docker compose exec weaviate \
  curl -s -X DELETE http://localhost:8080/v1/schema/MemberProfile
```

---

## Test OpenRouter connectivity from inside the container

```bash
docker compose exec matchbot python -c "
import os, httpx
r = httpx.get(
    'https://openrouter.ai/api/v1/models',
    headers={'Authorization': f'Bearer {os.environ[\"OPENROUTER_API_KEY\"]}'},
    timeout=10,
)
print(r.status_code, r.text[:200])
"
```

---

## Path B — bot on host, infra in Docker (for debugging with breakpoints)

```bash
# 1. Start only infrastructure
docker compose up -d mongo weaviate minio

# 2. Copy and inspect the local override file
cp .env.local.example .env.local   # points hostnames to localhost

# 3. Install deps locally
poetry install

# 4. Load all env files and run
set -a
source .env
source .env.bot
source .env.local   # must come last — overrides Docker service hostnames
set +a

poetry run python -m telegram_llm_bot.main
```

The first run downloads the `all-MiniLM-L6-v2` embedding model (~90 MB).
Subsequent runs are instant.
