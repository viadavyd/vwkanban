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
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER vwk
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn vwkanban.main:app --host 0.0.0.0 --port 8000 --workers 1 --ws-max-size 131072 --proxy-headers --forwarded-allow-ips '*'"]
