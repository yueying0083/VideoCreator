from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import COST_RATES
from app.database import Project, SessionLocal, get_db
from app.schemas import JobTaskOut, MusicGenerateRequest
from app.services.google_ai import generate_music
from app.services.storage import allocate_rel_path, to_media_url
from app.services.task_runner import create_job_record, record_cost, submit_background_job

router = APIRouter(prefix="/api/projects/{project_id}/audio", tags=["audio"])


@router.post("/bgm/generate", response_model=JobTaskOut)
async def generate_project_bgm(
    project_id: str,
    payload: MusicGenerateRequest,
    db: Session = Depends(get_db),
):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    est_cost = COST_RATES["music_pro"] if payload.mode == "pro" else COST_RATES["music_clip"]
    job = create_job_record(
        project_id=project_id,
        kind="music",
        message="正在调用 Lyria 3 生成专属电影配乐...",
        estimated_cost_usd=est_cost,
    )

    def _worker(progress_cb):
        progress_cb(35, f"Lyria 3 ({payload.mode}) 谱曲与音频渲染中...")
        rel_path, abs_path = allocate_rel_path(project_id, "audio", "mp3", prefix="bgm")
        _, model_used, is_demo = generate_music(payload.prompt, abs_path, mode=payload.mode)
        session = SessionLocal()
        try:
            p = session.get(Project, project_id)
            if p:
                p.bgm_path = rel_path
                p.bgm_prompt = payload.prompt
                session.commit()
        finally:
            session.close()
        record_cost(project_id, job.id, "music", model_used, est_cost, is_demo, f"Lyria 3 BGM ({payload.mode})")
        return {"bgm_url": to_media_url(rel_path), "is_demo": is_demo}

    submit_background_job(job.id, _worker)
    return JobTaskOut(
        id=job.id,
        project_id=job.project_id,
        shot_id=None,
        kind=job.kind,
        status=job.status,
        progress=job.progress,
        message=job.message,
        result=None,
        error=job.error,
        estimated_cost_usd=job.estimated_cost_usd,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post("/bgm/upload")
async def upload_project_bgm(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    ext = Path(file.filename or "bgm.mp3").suffix.lstrip(".") or "mp3"
    rel_path, abs_path = allocate_rel_path(project_id, "audio", ext, prefix="bgm_upload")
    abs_path.write_bytes(await file.read())
    proj.bgm_path = rel_path
    db.commit()
    return {"bgm_url": to_media_url(rel_path)}


@router.post("/subtitles/auto-from-script")
def generate_srt_from_shot_dialogues(
    project_id: str,
    episode_id: str | None = None,
    db: Session = Depends(get_db),
):
    """Generate clean SRT subtitles automatically aligned to selected shot durations and dialogues."""
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    def _fmt_ts(sec: float) -> str:
        ms = int(round((sec - int(sec)) * 1000))
        total = int(sec)
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    target_shots = [s for s in proj.shots if (not episode_id or s.episode_id == episode_id)]
    cursor = 0.0
    entries: list[str] = []
    idx = 1
    for shot in target_shots:
        dur = float(shot.duration_sec or 6)
        if shot.selected_take_id:
            sel = next((t for t in shot.takes if t.id == shot.selected_take_id), None)
            if sel:
                t_start = float(shot.trim_start or 0.0)
                t_end = float(shot.trim_end) if shot.trim_end else float(sel.duration_sec)
                dur = max(0.5, t_end - t_start)
        text = (shot.dialogue or "").strip()
        if text:
            start_s = cursor + 0.3
            end_s = max(start_s + 0.8, cursor + dur - 0.3)
            entries.append(f"{idx}\n{_fmt_ts(start_s)} --> {_fmt_ts(end_s)}\n{text}\n")
            idx += 1
        cursor += dur

    srt = "\n".join(entries)
    proj.subtitle_srt = srt
    db.commit()
    return {"subtitle_srt": srt}
