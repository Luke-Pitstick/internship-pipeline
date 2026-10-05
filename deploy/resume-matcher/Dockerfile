# Resume Matcher source contract pinned to the inspected commit.
FROM node:22-bookworm AS frontend-builder
ADD https://github.com/srbhr/Resume-Matcher/archive/63fc344a9a59a79db6fa9d96aff188dc9faf545b.tar.gz /tmp/upstream.tar.gz
RUN mkdir /upstream && tar -xzf /tmp/upstream.tar.gz -C /upstream --strip-components=1
WORKDIR /upstream/apps/frontend
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_API_URL=/
RUN npm ci && npm run build

FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 libatspi2.0-0 \
    libgtk-3-0 fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
COPY --from=frontend-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend-builder /upstream/apps/backend/pyproject.toml /app/backend/
COPY --from=frontend-builder /upstream/apps/backend/app /app/backend/app
COPY deploy/resume-matcher/pipeline_resume_api.py /app/backend/pipeline_resume_api.py
WORKDIR /app/backend
RUN pip install .
COPY --from=frontend-builder /upstream/apps/frontend/.next/standalone /app/frontend/
COPY --from=frontend-builder /upstream/apps/frontend/.next/static /app/frontend/.next/static
COPY --from=frontend-builder /upstream/apps/frontend/public /app/frontend/public
COPY --from=frontend-builder /upstream/docker/start.sh /app/start.sh
RUN sed -i 's/\r$//' /app/start.sh && \
    sed -i 's/app.main:app/pipeline_resume_api:app/' /app/start.sh && \
    chmod +x /app/start.sh && mkdir -p /app/backend/data && \
    useradd -m -u 1000 -s /bin/bash appuser && \
    mkdir -p /home/appuser/.ssh && chmod 0700 /home/appuser/.ssh && \
    chown -R appuser:appuser /app /home/appuser/.ssh
USER appuser
RUN python -m playwright install chromium
EXPOSE 3000
VOLUME ["/app/backend/data"]
WORKDIR /app
HEALTHCHECK --interval=10s --timeout=10s --start-period=30s --retries=5 \
    CMD curl -f http://127.0.0.1:8000/api/v1/health || exit 1
CMD ["/app/start.sh"]
