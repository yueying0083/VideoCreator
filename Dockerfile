# ==============================================================================
# Stage 1: Build React + Vite Frontend
# ==============================================================================
ARG NODE_IMAGE=node:20-alpine
ARG PYTHON_IMAGE=python:3.12-slim

FROM ${NODE_IMAGE} AS web-builder

ARG NPM_REGISTRY=""

WORKDIR /build/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
    && npm ci

COPY apps/web/ ./
RUN npm run build

# ==============================================================================
# Stage 2: Production Python 3.12 Runtime (FastAPI + FFmpeg + CJK Fonts + SPA)
# ==============================================================================
FROM ${PYTHON_IMAGE} AS runtime

ARG APT_MIRROR=""
ARG PIP_INDEX_URL=""
ARG PIP_TRUSTED_HOST=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STUDIO_DATA_DIR=/data \
    STUDIO_ENV_PATH=/data/runtime.env \
    STUDIO_WEB_DIR=/app/web_dist \
    TZ=Asia/Shanghai

# Install native FFmpeg (libx264/libass/libmp3lame) + lightweight Chinese font for Pillow & SRT burn-in
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null || true; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fontconfig \
    fonts-wqy-zenhei \
    curl \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY apps/api/requirements.docker.txt ./requirements.txt
RUN PIP_ARGS=""; \
    if [ -n "$PIP_INDEX_URL" ]; then PIP_ARGS="-i $PIP_INDEX_URL"; fi; \
    if [ -n "$PIP_TRUSTED_HOST" ]; then PIP_ARGS="$PIP_ARGS --trusted-host $PIP_TRUSTED_HOST"; fi; \
    pip install --no-cache-dir $PIP_ARGS --upgrade pip \
    && pip install --no-cache-dir $PIP_ARGS -r requirements.txt

COPY apps/api/app ./app
COPY --from=web-builder /build/web/dist /app/web_dist

RUN mkdir -p /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# Keep --workers 1 because background video generation tasks run in-process with local SQLite
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
