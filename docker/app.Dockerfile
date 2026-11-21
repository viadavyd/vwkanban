# Build context: backend/
FROM ghcr.io/astral-sh/uv:0.13.9 AS uv

FROM python:3.13.18-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13.18-slim
LABEL org.opencontainers.image.source=https://github.com/viadavyd/vwkanban
RUN useradd --system --uid 10001 --home /app vwk
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
# glibc gives each thread pool worker (argon2, CSV parsing) its own malloc arena and keeps
# it: under load the app's RSS climbed toward its 256m mem_limit. Two arenas keep it flat.
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 MALLOC_ARENA_MAX=2
USER vwk
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn vwkanban.main:app --host 0.0.0.0 --port 8000 --workers 1 --ws-max-size 131072 --proxy-headers --forwarded-allow-ips '*'"]
