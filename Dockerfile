FROM ghcr.io/astral-sh/uv:0.9.14 AS uv
FROM node:22-bookworm-slim AS codex
RUN npm install --prefix /opt/codex @openai/codex@0.153.0
FROM node:22-bookworm-slim AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS pipeline
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /opt/codex /opt/codex
RUN ln -s /opt/codex/node_modules/.bin/codex /usr/local/bin/codex
RUN apt-get update && apt-get install -y --no-install-recommends texlive-latex-extra texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && useradd --uid 10001 --create-home pipeline \
    && mkdir -p /var/data \
    && chown pipeline:pipeline /var/data
COPY --from=frontend /web/build /app/web/build
ENV PIPELINE_DATA_DIR=/var/data PIPELINE_WEB_DIR=/app/web/build CODEX_HOME=/var/data/codex
EXPOSE 8080
VOLUME ["/var/data"]
USER pipeline
ENTRYPOINT ["python", "-m", "internship_pipeline.bootstrap"]
