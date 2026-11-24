from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import ExportRecord, Project, SessionLocal, Shot, Take, get_db
from app.schemas import ExportOut, ExportRequest, JobTaskOut
from app.services.media_renderer import render_timeline_export
from app.services.storage import allocate_rel_path, resolve_abs_path, to_media_url
from app.services.task_runner import create_job_record, submit_background_job

router = APIRouter(prefix="/api/projects/{project_id}/exports", tags=["exports"])


def serialize_export(e: ExportRecord) -> ExportOut:
    abs_p = resolve_abs_path(e.file_path)
    return ExportOut(
        id=e.id,
        project_id=e.project_id,
        file_url=to_media_url(e.file_path) or "",
        local_path=str(abs_p) if abs_p else "",
        resolution=e.resolution,
        duration_sec=e.duration_sec,
        include_bgm=e.include_bgm,
        burn_subtitles=e.burn_subtitles,
        created_at=e.created_at,
    )


@router.get("", response_model=list[ExportOut])
def list_exports(project_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(ExportRecord)
        .filter(ExportRecord.project_id == project_id)
        .order_by(ExportRecord.created_at.desc())
        .all()
    )
    return [serialize_export(r) for r in rows]


@router.post("", response_model=JobTaskOut)
async def create_export(project_id: str, payload: ExportRequest, db: Session = Depends(get_db)):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    q = db.query(Shot).filter(Shot.project_id == project_id)
    if payload.episode_id:
        q = q.filter(Shot.episode_id == payload.episode_id)
    shots = q.order_by(Shot.order_index.asc(), Shot.created_at.asc()).all()

    clip_specs = []
    for shot in shots:
        take = None
        if shot.selected_take_id:
            take = db.get(Take, shot.selected_take_id)
        elif shot.takes:
            take = shot.takes[0]
        if not take:
            continue
        p = resolve_abs_path(take.file_path)
        if p and p.exists():
            clip_specs.append(
                {
                    "path": p,
                    "trim_start": shot.trim_start or 0.0,
                    "trim_end": shot.trim_end,
                    "duration_sec": take.duration_sec,
                    "has_audio": take.has_audio,
                }
            )

    if not clip_specs:
        raise HTTPException(status_code=400, detail="当前没有可导出的镜头视频，请先为分镜生成或导入视频。")

    bgm_abs = resolve_abs_path(proj.bgm_path) if payload.include_bgm else None
    srt_text = proj.subtitle_srt if payload.burn_subtitles else ""
    aspect_ratio = proj.aspect_ratio
    bgm_vol = proj.bgm_volume

    job = create_job_record(
        project_id=project_id,
        kind="export",
        message=f"本地 FFmpeg 正在合片导出 {len(clip_specs)} 个镜头 ({payload.resolution})...",
        estimated_cost_usd=0.0,
    )

    def _worker(progress_cb):
        progress_cb(30, f"FFmpeg 拼接 {len(clip_specs)} 个视频片段并处理音轨...")
        rel_out, abs_out = allocate_rel_path(project_id, "exports", "mp4", prefix=f"final_{payload.resolution}")
        final_dur = render_timeline_export(
            clips=clip_specs,
            output_path=abs_out,
            aspect_ratio=aspect_ratio,
            resolution=payload.resolution,
            bgm_path=bgm_abs,
            bgm_volume=bgm_vol,
            subtitle_srt=srt_text,
        )
        progress_cb(90, "记录成片档案...")
        session = SessionLocal()
        try:
            rec = ExportRecord(
                project_id=project_id,
                file_path=rel_out,
                resolution=payload.resolution,
                duration_sec=final_dur,
                include_bgm=bool(bgm_abs and bgm_abs.exists()),
                burn_subtitles=bool(srt_text and srt_text.strip()),
            )
            session.add(rec)
            session.commit()
            rec_id = rec.id
        finally:
            session.close()
        return {
            "export_id": rec_id,
            "file_url": to_media_url(rel_out),
            "local_path": str(abs_out),
            "duration_sec": final_dur,
        }

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
        estimated_cost_usd=0.0,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
