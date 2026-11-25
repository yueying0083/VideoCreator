from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import DATA_DIR, STATIC_WEB_DIR, get_cors_origins, is_auth_enabled
from app.database import init_db
from app.routers import assets, audio, auth, chat, export, novel, projects, settings, shots, studio, tasks
from app.services.auth import AuthGateMiddleware, ensure_env_admin_if_configured
from app.services.task_runner import attach_event_loop, mark_stale_jobs_on_startup


@asynccontextmanager
async def lifespan(_app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "projects").mkdir(parents=True, exist_ok=True)
    init_db()
    ensure_env_admin_if_configured()
    mark_stale_jobs_on_startup()
    attach_event_loop(asyncio.get_running_loop())
    yield


app = FastAPI(
    title="Video Creator Studio API",
    version="0.2.0",
    description="Local-First & Docker-Ready Personal AI Video Creation Studio powered by Google AI Stack",
    lifespan=lifespan,
)

# Register AuthGateMiddleware first so CORSMiddleware wraps it as outermost
app.add_middleware(AuthGateMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_PROJECTS_DIR = DATA_DIR / "projects"
MEDIA_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
# Expose ONLY generated/uploaded project media under /media/projects (never /data/runtime.env or studio.db)
app.mount("/media/projects", StaticFiles(directory=str(MEDIA_PROJECTS_DIR)), name="media-projects")

app.include_router(auth.router)
app.include_router(settings.router)
app.include_router(projects.router)
app.include_router(novel.router)
app.include_router(assets.router)
app.include_router(shots.router)
app.include_router(chat.router)
app.include_router(audio.router)
app.include_router(tasks.router)
app.include_router(export.router)
app.include_router(studio.router)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "auth_enabled": is_auth_enabled(),
    }


# Unified single-container SPA serving (Docker / production build)
if STATIC_WEB_DIR.exists() and (STATIC_WEB_DIR / "index.html").exists():
    assets_dir = STATIC_WEB_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="web-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api" or full_path.startswith("media/") or full_path == "media":
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (STATIC_WEB_DIR / full_path).resolve()
        if full_path and STATIC_WEB_DIR in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_WEB_DIR / "index.html")
