# ==============================================================================
# Stage 1: Build React + Vite Frontend
# ==============================================================================
FROM node:20-alpine AS web-builder

WORKDIR /build/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

COPY apps/web/ ./
RUN npm run build

# ==============================================================================
# Stage 2: Production Python 3.11 Runtime (FastAPI + FFmpeg + CJK Fonts + SPA)
# ==============================================================================
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STUDIO_DATA_DIR=/data \
    STUDIO_ENV_PATH=/data/runtime.env \
    STUDIO_WEB_DIR=/app/web_dist \
    TZ=Asia/Shanghai

# Install native FFmpeg (libx264/libass/libmp3lame) + lightweight Chinese font for Pillow & SRT burn-in
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fontconfig \
    fonts-wqy-zenhei \
    curl \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY apps/api/requirements.docker.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY apps/api/app ./app
COPY --from=web-builder /build/web/dist /app/web_dist

RUN mkdir -p /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# Keep --workers 1 because background video generation tasks run in-process with local SQLite
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
