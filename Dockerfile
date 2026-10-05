FROM ghcr.io/astral-sh/uv:0.9.14 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra sources --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra sources --no-editable \
    && useradd --uid 10001 --create-home pipeline \
    && mkdir -p /app/data /app/artifacts /app/config /app/private \
    && chown -R pipeline:pipeline /app/data /app/artifacts
USER pipeline
ENTRYPOINT ["internship-pipeline", "--config", "config/settings.local.yaml"]
CMD ["status"]
