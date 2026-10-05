FROM ghcr.io/astral-sh/uv:0.9.14 AS uv
FROM node:22-bookworm-slim AS codex
RUN npm install --prefix /opt/codex @openai/codex@0.153.0
FROM python:3.12-slim AS pipeline
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && useradd --uid 10001 --create-home pipeline \
    && mkdir -p /app/data /app/artifacts /app/config /app/private \
    && chown -R pipeline:pipeline /app/data /app/artifacts
USER pipeline
ENTRYPOINT ["internship-pipeline", "--config", "config/settings.local.yaml"]
CMD ["status"]

FROM pipeline AS render
USER root
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /opt/codex /opt/codex
RUN ln -s /opt/codex/node_modules/.bin/codex /usr/local/bin/codex
RUN usermod -s /bin/bash pipeline \
    && mkdir -p /home/pipeline/.ssh \
    && chmod 0700 /home/pipeline/.ssh \
    && chown pipeline:pipeline /home/pipeline/.ssh
COPY deploy/worker-entrypoint.py /app/worker-entrypoint.py
ENV CODEX_HOME=/var/data/codex
USER pipeline
ENTRYPOINT ["python", "/app/worker-entrypoint.py"]
