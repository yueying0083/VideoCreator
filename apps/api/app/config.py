from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from dotenv import dotenv_values, load_dotenv, set_key
from pydantic import BaseModel


def _resolve_repo_root() -> Path:
    here = Path(__file__).resolve()
    # Local monorepo layout: <repo>/apps/api/app/config.py
    if len(here.parents) >= 4 and (here.parents[3] / "apps").exists():
        return here.parents[3]
    # Docker container layout: /app/app/config.py
    return here.parents[1]


REPO_ROOT = _resolve_repo_root()
DATA_DIR = Path(os.environ.get("STUDIO_DATA_DIR", str(REPO_ROOT / "data"))).resolve()
DB_PATH = DATA_DIR / "studio.db"
ENV_PATH = Path(os.environ.get("STUDIO_ENV_PATH", str(REPO_ROOT / ".env"))).resolve()
STATIC_WEB_DIR = Path(
    os.environ.get("STUDIO_WEB_DIR", str(REPO_ROOT / "apps" / "web" / "dist"))
).resolve()

if ENV_PATH.exists():
    load_dotenv(ENV_PATH, override=False)


# Estimated USD unit costs (2026 Google AI + OpenAI pricing references)
COST_RATES = {
    "chat": 0.005,                 # per director agent turn (Gemini 4)
    "enhance": 0.003,              # per Omni prompt enhancement (Gemini 4)
    "qa": 0.01,                    # per video QA review
    "image": 0.055,                # per Nano Banana 2.1 / GPT Image generation
    "turnaround": 0.067,           # per 3-view character turnaround sheet
    "omni_flash_per_sec": 0.03,    # Gemini Omni 1.2 Flash estimated video cost/sec
    "music_clip": 0.04,            # Lyria 3 30s clip
    "music_pro": 0.08,             # Lyria 3 Pro full song
    "music_lyria35": 0.06,         # Lyria 3.5 music generation
}


def estimate_video_cost(engine: str, duration_sec: int, resolution: str = "720p") -> float:
    if engine in ("flow_import", "demo"):
        return 0.0
    mult = 1.5 if resolution.lower() == "4k" else 1.0
    return round(COST_RATES["omni_flash_per_sec"] * max(1, duration_sec) * mult, 3)


class RuntimeSettings(BaseModel):
    app_mode: Literal["auto", "live", "demo"] = "auto"
    gemini_api_key: str = ""
    image_provider: Literal["gemini", "openai_assets", "openai_all"] = "gemini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_image_model: str = "gpt-image-1"
    openai_max_concurrent: int = 2
    text_model: str = "gemini-4-hydrogen"
    image_model: str = "gemini-nano-banana-2.1"
    omni_video_model: str = "gemini-omni-1.2-flash"
    music_model: str = "lyria-3.5"
    max_concurrent_jobs: int = 3
    video_request_timeout: int = 900
    monthly_budget_usd: float = 40.0

    @property
    def effective_mode(self) -> Literal["live", "demo"]:
        if self.app_mode == "demo":
            return "demo"
        if self.app_mode == "live":
            return "live"
        return "live" if (self.gemini_api_key.strip() or self.openai_api_key.strip()) else "demo"

    @property
    def has_gemini_key(self) -> bool:
        return bool(self.gemini_api_key.strip())

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key.strip())

    def use_openai_for(self, purpose: str) -> bool:
        if self.image_provider == "openai_all":
            return True
        if self.image_provider == "openai_assets" and purpose in ("asset", "turnaround"):
            return True
        return False


ENV_KEY_MAP = {
    "app_mode": "APP_MODE",
    "gemini_api_key": "GEMINI_API_KEY",
    "image_provider": "IMAGE_PROVIDER",
    "openai_base_url": "OPENAI_BASE_URL",
    "openai_api_key": "OPENAI_API_KEY",
    "openai_image_model": "OPENAI_IMAGE_MODEL",
    "openai_max_concurrent": "OPENAI_MAX_CONCURRENT",
    "text_model": "TEXT_MODEL",
    "image_model": "IMAGE_MODEL",
    "omni_video_model": "OMNI_VIDEO_MODEL",
    "music_model": "MUSIC_MODEL",
    "max_concurrent_jobs": "MAX_CONCURRENT_JOBS",
    "video_request_timeout": "VIDEO_REQUEST_TIMEOUT",
    "monthly_budget_usd": "MONTHLY_BUDGET_USD",
}


def load_settings() -> RuntimeSettings:
    file_vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}

    def _get(env_name: str, default: str) -> str:
        # Prefer non-empty value from runtime env file (supports live edits & Docker UI persistence),
        # then fall back to container/process environment variables (docker-compose env_file / environment).
        file_val = file_vals.get(env_name)
        if file_val is not None and str(file_val).strip() != "":
            return str(file_val)
        env_val = os.environ.get(env_name)
        if env_val is not None and str(env_val).strip() != "":
            return str(env_val)
        return default

    app_mode = _get("APP_MODE", "auto").strip().lower()
    if os.environ.get("STUDIO_FORCE_DEMO") == "1":
        app_mode = "demo"
    if app_mode not in ("auto", "live", "demo"):
        app_mode = "auto"

    try:
        budget = float(_get("MONTHLY_BUDGET_USD", "40.0") or 40.0)
    except ValueError:
        budget = 40.0

    try:
        max_jobs = max(1, min(6, int(_get("MAX_CONCURRENT_JOBS", "3") or 3)))
    except ValueError:
        max_jobs = 3

    try:
        req_timeout = max(120, min(1800, int(_get("VIDEO_REQUEST_TIMEOUT", "900") or 900)))
    except ValueError:
        req_timeout = 900

    try:
        openai_conc = max(1, min(8, int(_get("OPENAI_MAX_CONCURRENT", "2") or 2)))
    except ValueError:
        openai_conc = 2

    openai_key = _get("OPENAI_API_KEY", "").strip()
    raw_img_provider = _get("IMAGE_PROVIDER", "").strip().lower()
    if raw_img_provider in ("gemini", "openai_assets", "openai_all"):
        img_provider = raw_img_provider
    else:
        img_provider = "openai_all" if openai_key else "gemini"

    return RuntimeSettings(
        app_mode=app_mode,  # type: ignore[arg-type]
        gemini_api_key=_get("GEMINI_API_KEY", "").strip(),
        image_provider=img_provider,  # type: ignore[arg-type]
        openai_base_url=_get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip() or "https://api.openai.com/v1",
        openai_api_key=openai_key,
        openai_image_model=_get("OPENAI_IMAGE_MODEL", "gpt-image-1").strip() or "gpt-image-1",
        openai_max_concurrent=openai_conc,
        text_model=_get("TEXT_MODEL", "gemini-4-hydrogen").strip() or "gemini-4-hydrogen",
        image_model=_get("IMAGE_MODEL", "gemini-nano-banana-2.1").strip() or "gemini-nano-banana-2.1",
        omni_video_model=_get("OMNI_VIDEO_MODEL", "gemini-omni-1.2-flash").strip() or "gemini-omni-1.2-flash",
        music_model=_get("MUSIC_MODEL", "lyria-3.5").strip() or "lyria-3.5",
        max_concurrent_jobs=max_jobs,
        video_request_timeout=req_timeout,
        monthly_budget_usd=budget,
    )


def save_settings_updates(updates: dict) -> RuntimeSettings:
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not ENV_PATH.exists():
        ENV_PATH.write_text("# Video Creator Studio runtime config\n", encoding="utf-8")

    conc_updated = False
    for field_name, value in updates.items():
        if value is None or field_name not in ENV_KEY_MAP:
            continue
        env_key = ENV_KEY_MAP[field_name]
        str_val = str(value).strip()
        # Keep existing secret if caller sent masked sentinel
        if field_name in ("gemini_api_key", "openai_api_key") and str_val.startswith("••••"):
            continue
        if field_name == "max_concurrent_jobs":
            str_val = str(max(1, min(6, int(value))))
        elif field_name == "openai_max_concurrent":
            str_val = str(max(1, min(8, int(value))))
            conc_updated = True
        elif field_name == "video_request_timeout":
            str_val = str(max(120, min(1800, int(value))))
        set_key(str(ENV_PATH), env_key, str_val, quote_mode="never")
        os.environ[env_key] = str_val

    try:
        os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass

    cfg = load_settings()
    if conc_updated:
        try:
            from app.services.task_runner import notify_openai_concurrency_changed

            notify_openai_concurrency_changed()
        except Exception:
            pass
    return cfg


def mask_secret(secret: str) -> str:
    s = secret.strip()
    if not s:
        return ""
    if len(s) <= 8:
        return "••••"
    return f"••••{s[-4:]}"


def _read_config_value(env_name: str, default: str = "") -> str:
    """Read config giving process os.environ precedence over runtime env file when explicitly set."""
    env_val = os.environ.get(env_name)
    if env_val is not None and str(env_val).strip() != "":
        return str(env_val).strip()
    file_vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    file_val = file_vals.get(env_name)
    if file_val is not None and str(file_val).strip() != "":
        return str(file_val).strip()
    return default


def is_auth_enabled() -> bool:
    raw = _read_config_value("AUTH_ENABLED", "true").lower()
    return raw not in ("0", "false", "no", "off")


def get_session_ttl_days() -> int:
    raw = _read_config_value("SESSION_TTL_DAYS", "14")
    try:
        return max(1, min(90, int(raw)))
    except ValueError:
        return 14


def get_cors_origins() -> list[str]:
    origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    extra = _read_config_value("CORS_ORIGINS", "")
    if extra:
        for item in extra.split(","):
            cleaned = item.strip().rstrip("/")
            if cleaned and cleaned != "*" and cleaned not in origins:
                origins.append(cleaned)
    return origins
