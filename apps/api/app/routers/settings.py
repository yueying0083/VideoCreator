from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import load_settings, mask_secret, save_settings_updates
from app.database import CostLog, get_db
from app.schemas import (
    BudgetSummary,
    ConnectionTestRequest,
    ConnectionTestResponse,
    SettingsOut,
    SettingsUpdate,
)
from app.services.genai_utils import test_gemini_connection
from app.services.media_renderer import get_ffmpeg_bin, get_ffprobe_bin

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _to_settings_out() -> SettingsOut:
    cfg = load_settings()
    ffmpeg = get_ffmpeg_bin()
    ffprobe = get_ffprobe_bin()
    return SettingsOut(
        app_mode=cfg.app_mode,
        effective_mode=cfg.effective_mode,
        has_gemini_key=cfg.has_gemini_key,
        gemini_api_key_masked=mask_secret(cfg.gemini_api_key),
        has_vertex_config=cfg.has_vertex_config,
        vertex_project_id=cfg.vertex_project_id,
        vertex_location=cfg.vertex_location,
        google_application_credentials=cfg.google_application_credentials,
        text_model=cfg.text_model,
        image_model=cfg.image_model,
        omni_video_model=cfg.omni_video_model,
        veo_lite_model=cfg.veo_lite_model,
        veo_fast_model=cfg.veo_fast_model,
        veo_standard_model=cfg.veo_standard_model,
        music_model=cfg.music_model,
        max_concurrent_jobs=cfg.max_concurrent_jobs,
        video_request_timeout=cfg.video_request_timeout,
        monthly_budget_usd=cfg.monthly_budget_usd,
        ffmpeg_available=bool(ffmpeg),
        ffprobe_available=bool(ffprobe),
        ffmpeg_path=ffmpeg or "",
    )


@router.get("", response_model=SettingsOut)
def get_settings():
    return _to_settings_out()


@router.put("", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate):
    save_settings_updates(payload.model_dump(exclude_none=True))
    return _to_settings_out()


@router.post("/test-connection", response_model=ConnectionTestResponse)
def test_connection(payload: ConnectionTestRequest | None = None):
    cfg = load_settings()
    ok, message, checked_model = test_gemini_connection(
        cfg,
        api_key_override=payload.gemini_api_key if payload else None,
    )
    return ConnectionTestResponse(ok=ok, message=message, checked_model=checked_model)


@router.get("/budget", response_model=BudgetSummary)
def get_budget_summary(db: Session = Depends(get_db)):
    cfg = load_settings()
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    live_total = (
        db.query(func.coalesce(func.sum(CostLog.cost_usd), 0.0))
        .filter(CostLog.created_at >= month_start, CostLog.is_demo.is_(False))
        .scalar()
        or 0.0
    )
    demo_total = (
        db.query(func.coalesce(func.sum(CostLog.cost_usd), 0.0))
        .filter(CostLog.created_at >= month_start, CostLog.is_demo.is_(True))
        .scalar()
        or 0.0
    )

    budget = max(1.0, float(cfg.monthly_budget_usd))
    remaining = max(0.0, round(budget - float(live_total), 3))
    pct = min(100.0, round((float(live_total) / budget) * 100.0, 1))

    return BudgetSummary(
        month=now.strftime("%Y-%m"),
        spent_usd=round(float(live_total), 3),
        demo_simulated_usd=round(float(demo_total), 3),
        monthly_budget_usd=budget,
        remaining_usd=remaining,
        percent_used=pct,
    )
