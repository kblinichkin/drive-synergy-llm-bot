# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# System deps for poetry
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install poetry
RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s /root/.local/bin/poetry /usr/local/bin/poetry

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Install dependencies (no dev deps, no root package yet)
RUN poetry config virtualenvs.create false && \
    poetry lock && \
    poetry install --only main --no-root --no-interaction --no-ansi

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm

WORKDIR /app

# Runtime system packages:
#   antiword  — legacy .doc file parsing (plain-text extraction)
#   curl      — used by healthchecks and minio client
RUN apt-get update && apt-get install -y --no-install-recommends \
    antiword \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY src/ ./src/
COPY logging.conf ./

ENV PYTHONPATH=/app/src

# Create logs directory
RUN mkdir -p /app/logs

# Non-root user for security
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

CMD ["python", "-m", "telegram_llm_bot.main"]
