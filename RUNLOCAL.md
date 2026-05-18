# Running the bot locally (after placeholders are filled)

Assumes you've already replaced the placeholders in `.env.bot`:
`TELEGRAM_BOT_TOKEN`, `OPENROUTER_API_KEY`, and `ADMIN_TELEGRAM_IDS`.

You have two paths. Pick A for the fewest moving parts; pick B if you want to
step through the bot in a debugger.

---

## Path A — everything in Docker (recommended)

The four services (`mongo`, `weaviate`, `minio`, `matchbot`) run together,
read env from `.env` + `.env.bot`, and talk to each other by service name.

```bash
# 1. From the project root
cd /path/to/drive-synergy-llm-bot

# 2. Make sure Docker Desktop / the Docker daemon is running, then:
docker compose build matchbot          # builds the bot image (first time ~3 min)
docker compose up -d mongo weaviate minio
docker compose ps                      # wait until all three show (healthy)

# 3. Start the bot in the foreground so you see logs in real time
docker compose up matchbot
```

You should see, in order:
- `Starting MatchBot (model=anthropic/claude-3-haiku)...`
- `MongoDB indexes ensured.`
- `Weaviate schema ensured.`
- `MinIO bucket ensured.`
- `Bot commands registered.`
- `MatchBot ready ✓`

If any of those lines fail, check `docker compose logs matchbot`
and `docker compose logs <service>` for the one that errored.

**First test — just talk to the bot:**
1. In Telegram, open a private chat with your bot (find it by its `@username`).
2. Send `/start` — you should get the welcome message.
3. Send `/help` — you should get the commands list.
   This exercises: polling → handler dispatch → reply. No LLM, no stores.

**Second test — full LLM round-trip:**
1. Send `/register`.
2. Upload a real PDF/DOCX resume (any CV will do).
3. In the logs you'll see a DEBUG line like:
   `OpenRouter extraction: model=anthropic/claude-3-haiku tokens_in=… tokens_out=… latency=…s`
4. The bot replies with an extracted preview. Reply `yes`.
5. Send `/find React developer interested in fintech` — the matchmaking prompt
   runs and you should see:
   `OpenRouter matchmaking: model=… tokens_in=… tokens_out=… latency=…s`

**To stop everything cleanly:**
```bash
docker compose down                 # stops containers, keeps data volumes
docker compose down -v              # also wipes mongo/weaviate/minio data
```

**Inspecting data while the bot runs:**
- MinIO console: http://localhost:9001 — login `minioadmin` / `minioadmin`.
- Mongo shell: `docker compose exec mongo mongosh matchbot` → `db.users.find().pretty()`.
- Weaviate: `curl http://localhost:8080/v1/schema` — should show the `MemberProfile` class.

---

## Path B — bot on host, infra in Docker (better for debugging)

Useful if you want to set breakpoints, use `pdb`, or reload on code change
without rebuilding the image.

```bash
# 1. Start only the infra containers
docker compose up -d mongo weaviate minio

# 2. Create a host-side env override so the bot talks to localhost, not docker DNS
cp .env.local.example .env.local
# (values there already point at localhost; no edits needed)

# 3. Install Python deps on the host
poetry install

# 4. Launch the bot on the host, merging all three env files
set -a
source .env            # mongo URI etc.
source .env.bot        # telegram token, openrouter key, bot settings
source .env.local      # localhost overrides — MUST come last to win
set +a

poetry run python -m telegram_llm_bot.main
```

Note on shells:
- On macOS / Linux, `set -a` + `source` is the standard trick to export every
  variable the `.env*` file defines.
- On Windows PowerShell you can use `Get-Content .env | ForEach-Object { $kv = $_ -split '=',2; [Environment]::SetEnvironmentVariable($kv[0],$kv[1]) }` for each file, or just run Path A.

The first run downloads the `all-MiniLM-L6-v2` sentence-transformer model
(~90 MB) — you'll see a progress bar. Subsequent runs are instant.

---

## Useful one-liners for debugging the LLM specifically

```bash
# Tail only the bot's logs inside Docker, colorized
docker compose logs -f matchbot | grep -E "OpenRouter|ERROR|extraction|matchmaking"

# Reset only the vector DB (keeps user registry in Mongo)
docker compose exec weaviate curl -X DELETE http://localhost:8080/v1/schema/MemberProfile

# Confirm the bot can actually reach OpenRouter from inside the container
docker compose exec matchbot python -c "
import os, httpx
r = httpx.get('https://openrouter.ai/api/v1/models',
              headers={'Authorization': f\"Bearer {os.environ['OPENROUTER_API_KEY']}\"},
              timeout=10)
print(r.status_code, r.text[:200])
"
```

---

## Common gotchas

- **`pydantic-settings ValidationError: openrouter_api_key Field required`**
  `.env.bot` isn't being read. Check that you're running from the project
  root and that compose includes `env_file: [.env, .env.bot]` (it does).
- **`getaddrinfo failed: 'weaviate'`** — you're on Path B but didn't load
  `.env.local` — the bot is using the compose DNS name. Re-source the file.
- **Telegram `Unauthorized: 401`** — placeholder token in `.env.bot`. Fix it.
- **OpenRouter `401 Unauthorized`** — invalid `OPENROUTER_API_KEY`.
- **`ModuleNotFoundError: No module named 'yaml'`** — you're on an old
  version of the code where `main.py` still imported PyYAML. Pull the latest.
- **Bot says "Unsupported file format" for a valid PDF** — the file might
  be a scanned image (no selectable text). Confirm by selecting text in a
  PDF viewer; if you can't select, antiword / pymupdf can't extract it.

---

## What changed in the code for this local-run pass

- `main.py` now parses `logging.conf` with `fileConfig` (INI format), and
  also writes logs to stdout at `DEBUG` — you'll actually see them now.
- All Weaviate calls in `storage/weaviate_client.py` are wrapped in
  `loop.run_in_executor(…)` so one slow search can't freeze the bot.
- `pipeline/ingestion.py::ingest_resume` now returns a typed
  `IngestionResult` dataclass instead of an untyped 5-tuple.
- `storage/minio_client.py` gained a `delete_resume()` helper; `/delete`
  now removes the resume file from MinIO in addition to Mongo + Weaviate.
- `config/prompts.py` dropped the unused `PROFILE_PREVIEW_TEMPLATE`.
- `.env.bot` inline comments on `SEARCH_TOP_K` / `SEARCH_RETURN_TOP` moved
  above the line so no parser ever trips on them.
- New `.env.local.example` for Path B.
