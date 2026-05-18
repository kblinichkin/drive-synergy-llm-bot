# Local-run audit — what will bite you before the bot starts

Scope: full stack via `docker compose up`, with a focus on the LLM round-trip working.
This is an audit only — no code changes have been made.

---

## 🔴 Blockers (bot will not start, or LLM will reject the call)

### 1. LLM provider mismatch — you have an Anthropic key, the code wants OpenRouter
- `CLAUDE.md` specifies the Anthropic SDK with `ANTHROPIC_API_KEY`.
- The actual code (`pipeline/extractor.py`, `matching/agent.py`) uses the **OpenAI SDK pointed at OpenRouter**, reading `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`.
- `pyproject.toml` has `openai = "^1.12.0"` but **no `anthropic` package**.
- `.env.bot` contains `OPENROUTER_API_KEY=sk-or-v1-your-key-here`.
- `settings.py` field `openrouter_api_key: str` is **required** (no default) — so Settings() will raise `ValidationError` at import time if the env var is missing.

You have two options — pick one before running anything:
- **Option A (matches current code, fastest to run):** create an OpenRouter account, generate a key at https://openrouter.ai/keys, put it in `.env.bot` as `OPENROUTER_API_KEY=…`, keep `OPENROUTER_MODEL=anthropic/claude-3-haiku`. Your existing Anthropic key is ignored.
- **Option B (matches CLAUDE.md spec, slower):** swap `openai` → `anthropic` SDK in `extractor.py` and `agent.py`, add `anthropic` to `pyproject.toml`, rename env vars to `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL`. Then your existing Anthropic key works directly.

Files that need to change if you pick Option B:
`pipeline/extractor.py:79-88, 99-113`, `matching/agent.py:43-51, 96-113`, `config/settings.py:23-32`, `.env.bot:19-29`, `pyproject.toml:15-16`.

### 2. `logging.conf` is INI-format but `main.py` parses it as YAML
`main.py:43-52` does:
```python
with open("logging.conf", "r") as f:
    config = yaml.safe_load(f)
logging.config.dictConfig(config)
```
…but `logging.conf` is a classic `[loggers] … [handlers]` INI file. `yaml.safe_load` won't raise `FileNotFoundError`, so the `try/except FileNotFoundError` fallback **will not catch it** — you'll get a `TypeError: dictConfig arg must be a Mapping` (or a `YAMLError`) and the bot will crash on boot.

Two fixes:
- Replace `yaml.safe_load` + `dictConfig` with `logging.config.fileConfig("logging.conf")`, or
- Convert `logging.conf` to YAML.

Note also that `logging.conf` as written sends everything to `logs/app.log` at `ERROR` level — you will see **nothing in stdout**, which is unhelpful for local debugging. You probably want a stdout handler at `DEBUG` while iterating.

### 3. `.env.bot` uses placeholder values for required fields
- `TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here` — the Telegram Application builder will call `getMe` at startup and fail immediately. You selected "no" for Telegram token availability in the preflight questions; the bot can't start at all without one.
- `OPENROUTER_API_KEY=sk-or-v1-your-key-here` — required field (see #1).
- `ADMIN_TELEGRAM_IDS=123456789,987654321` — placeholder, replace with your own Telegram user ID.

Recommendation: to test the LLM round-trip end-to-end without a Telegram token, run just the extractor as a script. I can add one if you want; it bypasses everything except `settings.py` → `extractor.py`.

### 4. `weaviate-client` v4 calls are sync, but wrapped in `async def`
`storage/weaviate_client.py`:
- `upsert_member_profile`, `get_profile_uuid_by_telegram_id`, `delete_member_profile`, `hybrid_search` are all `async def`, but every internal call (`collection.data.insert`, `collection.query.hybrid`, etc.) is **synchronous** and blocks the event loop.
- Functionally it will work, but under load each search will freeze the whole bot for the duration of the Weaviate call. Not a blocker for local debug, but worth knowing.

---

## 🟡 High-risk things that will surface as soon as you hit them

### 5. `ingest_resume` type hint lies about its return
`pipeline/ingestion.py:28-35` declares `-> ExtractedProfile`, but line 69 returns a **5-tuple** `(profile, profile_dict, vector, file_bytes, filename)`. The caller in `handlers/registration.py:101` correctly unpacks it, so it works — but any type checker or future refactor will be misleading.

### 6. `connect_to_local` hostname won't resolve outside Docker
`WEAVIATE_HOST=weaviate`, `MONGODB_URI=mongodb://mongo:27017`, `MINIO_ENDPOINT=minio:9000` — all of these are **Docker service names**, resolved only inside the compose network. If you ever run the bot process on your host (poetry run …) while the infra runs in docker, override these to `localhost` in a separate `.env.local`.

Inside compose (your chosen path) everything is fine.

### 7. Inline comments in `.env.bot` may or may not be stripped
Lines like `SEARCH_TOP_K=10        # candidates fetched from Weaviate before LLM re-rank` are parsed by `python-dotenv`, which **does** strip inline comments when the `#` is preceded by whitespace — so this should work. But pydantic-settings' default parser has bitten people here before. If you see `ValidationError: value is not a valid integer` for `search_top_k` or `embedding_dims`, the inline comment is the reason. Remove them.

### 8. `PROFILE_PREVIEW_TEMPLATE` in `prompts.py` is dead code
Not a bug — `registration.py:117-121` builds the preview inline via `profile.format_preview()` and ignores the template in `prompts.py`. Just confusing if you edit one and wonder why nothing changes.

### 9. `/delete` removes MongoDB soft-delete, but does it clean Weaviate + MinIO?
I didn't read `handlers/commands.py` in full, but from the storage-layer API: `delete_user()` in `mongo_client.py` only sets `profile_status="deleted"`. It does **not** call `delete_member_profile` in Weaviate or remove the MinIO object. Worth a look before shipping — deleted users will still show up in `/find` results.

---

## 🟢 Things that look healthy

- `compose.yaml` structure is clean, healthchecks are correct, service names match env vars. `mongo`, `weaviate`, `minio`, `matchbot` will start in order.
- `Dockerfile` multistage build with non-root user is sensible. `antiword` is installed for `.doc` support, matching `parser.py`.
- `pipeline/parser.py` has sane fallbacks for PDF/DOCX/DOC, strips control chars, handles the common "scanned PDF" failure with a clear error.
- `pipeline/embedder.py` caches the model via `lru_cache`, normalizes embeddings — matches what Weaviate hybrid search expects.
- `weaviate_client.ensure_schema()` is idempotent, correct v4 API for collection creation with `Configure.Vectorizer.none()`.
- The `ConversationHandler` FSM in `registration.py` is well-structured: `allow_reentry=True`, proper `_clear_context`, `/cancel` fallback, handles both `yes`/`no` regex.
- `EXTRACTION_SYSTEM_PROMPT` instructs the LLM to return pure JSON, and `_parse_json_response` strips accidental ```json fences. Matchmaking prompt with the `--- RANK: …` block format is parseable and robust.

---

## Recommended order to actually test LLM responsiveness

1. **Fix blockers #1 and #2 first** — without them the process won't start. Pick Option A (easier) or Option B (matches spec).
2. Put a real Telegram bot token and your Telegram user ID in `.env.bot`.
3. `docker compose up mongo weaviate minio -d` first; wait until all three report `(healthy)` in `docker ps`.
4. `docker compose up matchbot` in the foreground so you can see logs.
5. Message the bot in private chat: `/start` → `/register` → upload a small PDF. Watch the logs for the OpenRouter/Anthropic call latency + token count (logged at DEBUG).
6. After one successful `/register`, try `/find fullstack engineer with django experience` to exercise the matchmaking prompt.

If you want a faster feedback loop *just* for the LLM prompts (no Telegram, no Docker), I can write a standalone `scripts/check_llm.py` that loads `EXTRACTION_SYSTEM_PROMPT` and `MATCHMAKING_SYSTEM_PROMPT`, runs them against hardcoded resume text + mock candidates, and prints the response. That's often the fastest way to iterate on prompt quality.
