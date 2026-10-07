FROM ghcr.io/astral-sh/uv:0.9.14 AS uv
FROM --platform=$BUILDPLATFORM node:22-bookworm-slim AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run check && npm run build

FROM python:3.12-slim-bookworm AS pipeline
ARG IMAGE_VERSION=0.1.0
ARG IMAGE_REVISION=local
ARG IMAGE_SOURCE
LABEL org.opencontainers.image.title="Internship Pipeline" \
    org.opencontainers.image.version=$IMAGE_VERSION \
    org.opencontainers.image.revision=$IMAGE_REVISION \
    org.opencontainers.image.source=$IMAGE_SOURCE
COPY --from=uv /uv /usr/local/bin/uv
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
ENV PIPELINE_DATA_DIR=/var/data PIPELINE_WEB_DIR=/app/web/build
EXPOSE 8080
VOLUME ["/var/data"]
USER pipeline
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s CMD python -c "import os,urllib.request,urllib.parse; origin=os.environ.get('PIPELINE_ORIGIN','http://localhost:8080'); urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8080/readyz',headers={'Host':urllib.parse.urlsplit(origin).netloc}),timeout=3)"
ENTRYPOINT ["python", "-m", "internship_pipeline.bootstrap"]
