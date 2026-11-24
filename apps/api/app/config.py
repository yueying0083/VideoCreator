from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from dotenv import dotenv_values, load_dotenv, set_key
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = REPO_ROOT / ".env"
DATA_DIR = REPO_ROOT / "data"
DB_PATH = DATA_DIR / "studio.db"

if ENV_PATH.exists():
    load_dotenv(ENV_PATH, override=False)


# Estimated USD unit costs (2026 Google AI pricing references)
COST_RATES = {
    "chat": 0.005,              # per director agent turn (Gemini Flash/Pro)
    "qa": 0.01,                 # per video QA review
    "image": 0.055,             # per Nano Banana 2 (1K-2K) generation
    "turnaround": 0.067,        # per 3-view character turnaround sheet
    "veo_lite_per_sec": 0.05,   # Veo 3.1 Lite
    "veo_fast_per_sec": 0.12,   # Veo 3.1 Fast
    "veo_standard_per_sec": 0.40,  # Veo 3.1 Standard
    "omni_flash_per_sec": 0.03, # Gemini Omni 1.2 Flash estimated video cost/sec
    "music_clip": 0.04,         # Lyria 3 30s clip
    "music_pro": 0.08,          # Lyria 3 Pro full song
}


def estimate_video_cost(engine: str, duration_sec: int) -> float:
    if engine in ("flow_import", "demo"):
        return 0.0
    rate_map = {
        "veo_lite": COST_RATES["veo_lite_per_sec"],
        "veo_fast": COST_RATES["veo_fast_per_sec"],
        "veo_standard": COST_RATES["veo_standard_per_sec"],
        "omni_flash": COST_RATES["omni_flash_per_sec"],
    }
    return round(rate_map.get(engine, 0.05) * max(1, duration_sec), 3)


class RuntimeSettings(BaseModel):
    app_mode: Literal["auto", "live", "demo"] = "auto"
    gemini_api_key: str = ""
    vertex_project_id: str = ""
    vertex_location: str = "us-central1"
    google_application_credentials: str = ""
    text_model: str = "gemini-2.5-flash"
    image_model: str = "gemini-3.1-flash-image"
    omni_video_model: str = "gemini-omni-1.2-flash"
    veo_lite_model: str = "veo-3.1-lite-generate-001"
    veo_fast_model: str = "veo-3.1-fast-generate-001"
    veo_standard_model: str = "veo-3.1-generate-001"
    music_model: str = "lyria-3-clip-preview"
    monthly_budget_usd: float = 40.0

    @property
    def effective_mode(self) -> Literal["live", "demo"]:
        if self.app_mode == "demo":
            return "demo"
        if self.app_mode == "live":
            return "live"
        return "live" if (self.gemini_api_key.strip() or self.vertex_project_id.strip()) else "demo"

    @property
    def has_gemini_key(self) -> bool:
        return bool(self.gemini_api_key.strip())

    @property
    def has_vertex_config(self) -> bool:
        return bool(self.vertex_project_id.strip())


ENV_KEY_MAP = {
    "app_mode": "APP_MODE",
    "gemini_api_key": "GEMINI_API_KEY",
    "vertex_project_id": "VERTEX_PROJECT_ID",
    "vertex_location": "VERTEX_LOCATION",
    "google_application_credentials": "GOOGLE_APPLICATION_CREDENTIALS",
    "text_model": "TEXT_MODEL",
    "image_model": "IMAGE_MODEL",
    "omni_video_model": "OMNI_VIDEO_MODEL",
    "veo_lite_model": "VEO_LITE_MODEL",
    "veo_fast_model": "VEO_FAST_MODEL",
    "veo_standard_model": "VEO_STANDARD_MODEL",
    "music_model": "MUSIC_MODEL",
    "monthly_budget_usd": "MONTHLY_BUDGET_USD",
}


def load_settings() -> RuntimeSettings:
    file_vals = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}

    def _get(env_name: str, default: str) -> str:
        val = file_vals.get(env_name)
        if val is not None:
            return str(val)
        return os.environ.get(env_name, default)

    app_mode = _get("APP_MODE", "auto").strip().lower()
    if os.environ.get("STUDIO_FORCE_DEMO") == "1":
        app_mode = "demo"
    if app_mode not in ("auto", "live", "demo"):
        app_mode = "auto"

    try:
        budget = float(_get("MONTHLY_BUDGET_USD", "40.0") or 40.0)
    except ValueError:
        budget = 40.0

    creds_path = _get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if creds_path:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path

    return RuntimeSettings(
        app_mode=app_mode,  # type: ignore[arg-type]
        gemini_api_key=_get("GEMINI_API_KEY", "").strip(),
        vertex_project_id=_get("VERTEX_PROJECT_ID", "").strip(),
        vertex_location=_get("VERTEX_LOCATION", "us-central1").strip() or "us-central1",
        google_application_credentials=creds_path,
        text_model=_get("TEXT_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash",
        image_model=_get("IMAGE_MODEL", "gemini-3.1-flash-image").strip() or "gemini-3.1-flash-image",
        omni_video_model=_get("OMNI_VIDEO_MODEL", "gemini-omni-1.2-flash").strip() or "gemini-omni-1.2-flash",
        veo_lite_model=_get("VEO_LITE_MODEL", "veo-3.1-lite-generate-001").strip() or "veo-3.1-lite-generate-001",
        veo_fast_model=_get("VEO_FAST_MODEL", "veo-3.1-fast-generate-001").strip() or "veo-3.1-fast-generate-001",
        veo_standard_model=_get("VEO_STANDARD_MODEL", "veo-3.1-generate-001").strip() or "veo-3.1-generate-001",
        music_model=_get("MUSIC_MODEL", "lyria-3-clip-preview").strip() or "lyria-3-clip-preview",
        monthly_budget_usd=budget,
    )


def save_settings_updates(updates: dict) -> RuntimeSettings:
    if not ENV_PATH.exists():
        ENV_PATH.write_text("# Video Creator Studio local config\n", encoding="utf-8")

    for field_name, value in updates.items():
        if value is None or field_name not in ENV_KEY_MAP:
            continue
        env_key = ENV_KEY_MAP[field_name]
        str_val = str(value).strip()
        # Keep existing secret if caller sent masked sentinel
        if field_name == "gemini_api_key" and str_val.startswith("••••"):
            continue
        set_key(str(ENV_PATH), env_key, str_val, quote_mode="never")
        os.environ[env_key] = str_val

    return load_settings()


def mask_secret(secret: str) -> str:
    s = secret.strip()
    if not s:
        return ""
    if len(s) <= 8:
        return "••••"
    return f"••••{s[-4:]}"
