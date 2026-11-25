from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import COST_RATES, estimate_video_cost, load_settings
from app.database import Asset, Project, SessionLocal, Shot, StudioJob, Take, get_db
from app.schemas import (
    AssetOut,
    EnhancePromptRequest,
    EnhancedPromptOutput,
    ExtractFrameRequest,
    StudioJobCreateRequest,
    StudioJobOut,
    TakeOut,
)
from app.routers.assets import serialize_asset
from app.routers.shots import serialize_take
from app.services.genai_utils import sanitize_error
from app.services.media_renderer import (
    extract_video_frame,
    generate_thumbnail,
    inspect_media,
    probe_media_info,
)
from app.services.omni_engine import enhance_omni_prompt, generate_omni_video, validate_omni_request
from app.services.storage import allocate_rel_path, resolve_abs_path, to_media_url
from app.services.task_runner import publish_event, record_cost, submit_studio_worker

router = APIRouter(prefix="/api/projects/{project_id}/studio", tags=["studio"])


def _loads_list(raw: str | None) -> list[str]:
    try:
        val = json.loads(raw or "[]")
        return list(val) if isinstance(val, list) else []
    except Exception:
        return []


def serialize_studio_job(j: StudioJob) -> StudioJobOut:
    return StudioJobOut(
        id=j.id,
        project_id=j.project_id,
        mode=j.mode,
        status=j.status,
        progress=int(j.progress or 0),
        progress_message=j.progress_message or "",
        prompt=j.prompt,
        enhanced_prompt=j.enhanced_prompt,
        model=j.model,
        aspect_ratio=j.aspect_ratio,
        duration_seconds=int(j.duration_seconds),
        resolution=j.resolution,
        strip_audio=bool(j.strip_audio),
        task_override=j.task_override,
        first_frame_asset_id=j.first_frame_asset_id,
        last_frame_asset_id=j.last_frame_asset_id,
        source_video_asset_id=j.source_video_asset_id,
        ref_image_asset_ids=_loads_list(j.ref_image_asset_ids_json),
        ref_video_asset_ids=_loads_list(j.ref_video_asset_ids_json),
        parent_job_id=j.parent_job_id,
        previous_interaction_id=j.previous_interaction_id,
        interaction_id=j.interaction_id,
        output_url=to_media_url(j.output_file_path),
        output_thumb_url=to_media_url(j.output_thumb_path),
        output_duration_seconds=j.output_duration_seconds,
        output_width=j.output_width,
        output_height=j.output_height,
        output_has_audio=bool(j.output_has_audio),
        output_size_bytes=j.output_size_bytes,
        cost_usd=float(j.cost_usd or 0.0),
        error_message=j.error_message,
        created_at=j.created_at,
        updated_at=j.updated_at,
        completed_at=j.completed_at,
    )


def _publish_studio_job(job: StudioJob) -> None:
    publish_event("studio_job_update", serialize_studio_job(job).model_dump(mode="json"))


@router.post("/enhance-prompt", response_model=EnhancedPromptOutput)
def api_enhance_prompt(project_id: str, req: EnhancePromptRequest, db: Session = Depends(get_db)):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        out, model_used, is_demo = enhance_omni_prompt(req)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_error(e))
    record_cost(project_id, None, "enhance", model_used, COST_RATES["enhance"], is_demo, "Gemini 4 提示词扩写")
    return out


@router.get("/jobs", response_model=list[StudioJobOut])
def list_studio_jobs(project_id: str, limit: int = 80, db: Session = Depends(get_db)):
    rows = (
        db.query(StudioJob)
        .filter(StudioJob.project_id == project_id)
        .order_by(StudioJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return [serialize_studio_job(r) for r in rows]


@router.post("/jobs", response_model=StudioJobOut)
def create_studio_job(project_id: str, payload: StudioJobCreateRequest, db: Session = Depends(get_db)):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    cfg = load_settings()
    previous_interaction_id = payload.previous_interaction_id
    if payload.parent_job_id and not previous_interaction_id:
        parent = db.query(StudioJob).filter(StudioJob.id == payload.parent_job_id, StudioJob.project_id == project_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="找不到父级创作任务。")
        if parent.interaction_id:
            previous_interaction_id = parent.interaction_id

    try:
        validate_omni_request(
            mode=payload.mode,
            duration_seconds=payload.duration_seconds,
            aspect_ratio=payload.aspect_ratio,
            resolution=payload.resolution,
            has_first_frame=bool(payload.first_frame_asset_id),
            has_last_frame=bool(payload.last_frame_asset_id),
            has_source_video=bool(payload.source_video_asset_id),
            ref_image_count=len(payload.ref_image_asset_ids),
            ref_video_count=len(payload.ref_video_asset_ids),
            previous_interaction_id=previous_interaction_id,
            task_override=payload.task_override,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    est_cost = estimate_video_cost("omni_flash", payload.duration_seconds, payload.resolution)

    job = StudioJob(
        project_id=project_id,
        mode=payload.mode,
        status="queued",
        progress=5,
        progress_message="任务已提交，等待执行...",
        prompt=payload.prompt.strip(),
        enhanced_prompt=payload.enhanced_prompt.strip() if payload.enhanced_prompt else None,
        model=cfg.omni_video_model,
        aspect_ratio=payload.aspect_ratio,
        duration_seconds=payload.duration_seconds,
        resolution=payload.resolution,
        strip_audio=payload.strip_audio,
        task_override=payload.task_override,
        first_frame_asset_id=payload.first_frame_asset_id,
        last_frame_asset_id=payload.last_frame_asset_id,
        source_video_asset_id=payload.source_video_asset_id,
        ref_image_asset_ids_json=json.dumps(payload.ref_image_asset_ids),
        ref_video_asset_ids_json=json.dumps(payload.ref_video_asset_ids),
        parent_job_id=payload.parent_job_id,
        previous_interaction_id=previous_interaction_id,
        cost_usd=0.0 if cfg.effective_mode == "demo" else est_cost,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    _publish_studio_job(job)

    job_id = job.id

    def _resolve_asset_paths(session: Session, ids: list[str]) -> tuple[list[Path], list[str | None]]:
        paths: list[Path] = []
        valid_ids: list[str | None] = []
        for aid in ids:
            a = session.get(Asset, aid)
            if not a:
                continue
            p = resolve_abs_path(a.file_path)
            if p and p.exists():
                paths.append(p)
                valid_ids.append(aid)
        return paths, valid_ids

    def _worker() -> None:
        def _update_status(status: str, pct: int, msg: str) -> None:
            s = SessionLocal()
            try:
                j = s.get(StudioJob, job_id)
                if j:
                    j.status = status
                    j.progress = pct
                    j.progress_message = msg
                    s.commit()
                    s.refresh(j)
                    _publish_studio_job(j)
            finally:
                s.close()

        s = SessionLocal()
        try:
            j = s.get(StudioJob, job_id)
            if not j:
                return
            first_path = None
            if j.first_frame_asset_id:
                fa = s.get(Asset, j.first_frame_asset_id)
                first_path = resolve_abs_path(fa.file_path) if fa else None

            last_path = None
            if j.last_frame_asset_id:
                la = s.get(Asset, j.last_frame_asset_id)
                last_path = resolve_abs_path(la.file_path) if la else None

            src_vid_path = None
            if j.source_video_asset_id:
                va = s.get(Asset, j.source_video_asset_id)
                src_vid_path = resolve_abs_path(va.file_path) if va else None

            ref_img_paths, ref_img_ids = _resolve_asset_paths(s, _loads_list(j.ref_image_asset_ids_json))
            ref_vid_paths, ref_vid_ids = _resolve_asset_paths(s, _loads_list(j.ref_video_asset_ids_json))

            active_prompt = (j.enhanced_prompt or j.prompt).strip()
            mode = j.mode
            dur = int(j.duration_seconds)
            ar = j.aspect_ratio
            res = j.resolution
            strip_aud = bool(j.strip_audio)
            prev_iid = j.previous_interaction_id
            task_ov = j.task_override
            first_id = j.first_frame_asset_id
            last_id = j.last_frame_asset_id
            src_vid_id = j.source_video_asset_id
        finally:
            s.close()

        try:
            rel_out, abs_out = allocate_rel_path(project_id, "studio", "mp4", prefix=f"omni_{job_id}")
            _, model_used, is_demo, new_iid = generate_omni_video(
                prompt_en=active_prompt,
                output_path=abs_out,
                mode=mode,
                duration_sec=dur,
                aspect_ratio=ar,
                resolution=res,
                start_frame_path=first_path,
                end_frame_path=last_path,
                source_video_path=src_vid_path,
                ref_image_paths=ref_img_paths,
                ref_video_paths=ref_vid_paths,
                first_frame_asset_id=first_id,
                last_frame_asset_id=last_id,
                source_video_asset_id=src_vid_id,
                ref_image_asset_ids=ref_img_ids,
                ref_video_asset_ids=ref_vid_ids,
                strip_audio=strip_aud,
                previous_interaction_id=prev_iid,
                task_override=task_ov,
                badge_title=f"Omni Studio · {mode}",
                on_status=_update_status,
            )

            thumb_rel, thumb_abs = allocate_rel_path(project_id, "thumbs", "jpg", prefix=f"omni_{job_id}")
            thumb_ok = generate_thumbnail(abs_out, thumb_abs, kind="video")
            meta = inspect_media(abs_out)

            s2 = SessionLocal()
            try:
                j2 = s2.get(StudioJob, job_id)
                if j2:
                    j2.status = "completed"
                    j2.progress = 100
                    j2.progress_message = "生成完成"
                    j2.model = model_used
                    j2.interaction_id = new_iid
                    j2.output_file_path = rel_out
                    j2.output_thumb_path = thumb_rel if thumb_ok else None
                    j2.output_duration_seconds = meta.get("duration_seconds") or float(dur)
                    j2.output_width = meta.get("width")
                    j2.output_height = meta.get("height")
                    j2.output_has_audio = bool(meta.get("has_audio", not strip_aud))
                    j2.output_size_bytes = int(meta.get("size_bytes") or abs_out.stat().st_size)
                    j2.cost_usd = 0.0 if is_demo else est_cost
                    j2.error_message = None
                    j2.completed_at = datetime.now(timezone.utc)
                    s2.commit()
                    s2.refresh(j2)
                    _publish_studio_job(j2)
            finally:
                s2.close()

            record_cost(project_id, job_id, "studio_video", model_used, est_cost, is_demo, f"Omni Studio ({mode}, {dur}s {res})")
        except Exception as exc:
            err_msg = sanitize_error(exc)
            s_err = SessionLocal()
            try:
                je = s_err.get(StudioJob, job_id)
                if je:
                    je.status = "failed"
                    je.progress = 100
                    je.progress_message = "生成失败"
                    je.error_message = err_msg
                    s_err.commit()
                    s_err.refresh(je)
                    _publish_studio_job(je)
            finally:
                s_err.close()

    submit_studio_worker(_worker)
    return serialize_studio_job(job)


@router.get("/jobs/{job_id}", response_model=StudioJobOut)
def get_studio_job(project_id: str, job_id: str, db: Session = Depends(get_db)):
    job = db.query(StudioJob).filter(StudioJob.id == job_id, StudioJob.project_id == project_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="创作任务不存在。")
    return serialize_studio_job(job)


@router.get("/jobs/{job_id}/lineage", response_model=list[StudioJobOut])
def get_studio_job_lineage(project_id: str, job_id: str, db: Session = Depends(get_db)):
    target = db.query(StudioJob).filter(StudioJob.id == job_id, StudioJob.project_id == project_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="创作任务不存在。")

    chain: list[StudioJob] = [target]
    seen = {target.id}
    curr = target
    while curr.parent_job_id:
        if curr.parent_job_id in seen:
            break
        parent = db.query(StudioJob).filter(StudioJob.id == curr.parent_job_id, StudioJob.project_id == project_id).first()
        if not parent:
            break
        chain.insert(0, parent)
        seen.add(parent.id)
        curr = parent

    children = (
        db.query(StudioJob)
        .filter(StudioJob.parent_job_id == job_id, StudioJob.project_id == project_id)
        .order_by(StudioJob.created_at.asc())
        .all()
    )
    for c in children:
        if c.id not in seen:
            chain.append(c)
            seen.add(c.id)

    return [serialize_studio_job(x) for x in chain]


@router.post("/jobs/{job_id}/extract-frame", response_model=AssetOut)
def extract_studio_job_frame(
    project_id: str,
    job_id: str,
    req: ExtractFrameRequest,
    db: Session = Depends(get_db),
):
    job = db.query(StudioJob).filter(StudioJob.id == job_id, StudioJob.project_id == project_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="创作任务不存在。")
    vid_abs = resolve_abs_path(job.output_file_path)
    if not vid_abs or not vid_abs.exists():
        raise HTTPException(status_code=400, detail="该任务尚未生成可抽帧的视频文件。")

    rel_path, abs_path = allocate_rel_path(project_id, "assets", "png", prefix=f"studio_frame_{job_id[:6]}")
    try:
        extract_video_frame(vid_abs, abs_path, position=req.position, timestamp_seconds=req.timestamp_seconds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    meta = inspect_media(abs_path)
    thumb_rel, thumb_abs = allocate_rel_path(project_id, "thumbs", "jpg", prefix=f"studio_frame_{job_id[:6]}")
    thumb_ok = generate_thumbnail(abs_path, thumb_abs, kind="image")
    label = {"first": "首帧", "last": "尾帧", "custom": f"{req.timestamp_seconds or 0:.1f}s帧"}.get(
        req.position, "关键帧"
    )

    asset = Asset(
        project_id=project_id,
        name=f"Omni_{job_id[:6]}_{label}",
        kind="scene",
        description=f"提取自 Omni 创作任务 {job_id[:6]}",
        file_path=rel_path,
        media_type="image",
        mime_type="image/png",
        thumb_path=thumb_rel if thumb_ok else None,
        size_bytes=int(meta.get("size_bytes") or abs_path.stat().st_size),
        width=meta.get("width"),
        height=meta.get("height"),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return serialize_asset(asset)


@router.post("/jobs/{job_id}/save-as-asset", response_model=AssetOut)
def save_studio_job_as_asset(project_id: str, job_id: str, db: Session = Depends(get_db)):
    job = db.query(StudioJob).filter(StudioJob.id == job_id, StudioJob.project_id == project_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="创作任务不存在。")
    vid_abs = resolve_abs_path(job.output_file_path)
    if not vid_abs or not vid_abs.exists():
        raise HTTPException(status_code=400, detail="该任务尚未生成视频文件。")

    rel_path, abs_path = allocate_rel_path(project_id, "assets", "mp4", prefix=f"studio_vid_{job_id[:6]}")
    shutil.copy2(vid_abs, abs_path)

    meta = inspect_media(abs_path)
    thumb_rel, thumb_abs = allocate_rel_path(project_id, "thumbs", "jpg", prefix=f"studio_vid_{job_id[:6]}")
    thumb_ok = generate_thumbnail(abs_path, thumb_abs, kind="video")

    asset = Asset(
        project_id=project_id,
        name=f"Omni作品_{job_id[:6]}",
        kind="video",
        description=f"来自全模态创作台：{job.prompt[:80]}",
        file_path=rel_path,
        media_type="video",
        mime_type="video/mp4",
        thumb_path=thumb_rel if thumb_ok else None,
        size_bytes=int(meta.get("size_bytes") or abs_path.stat().st_size),
        width=meta.get("width"),
        height=meta.get("height"),
        duration_sec=meta.get("duration_seconds"),
        fps=meta.get("fps"),
        has_audio=bool(meta.get("has_audio")),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return serialize_asset(asset)


@router.post("/jobs/{job_id}/send-to-shot/{shot_id}", response_model=TakeOut)
def send_studio_job_to_shot(
    project_id: str,
    job_id: str,
    shot_id: str,
    db: Session = Depends(get_db),
):
    """Promote a completed StudioJob video into a storyboard Shot as a selected Take."""
    job = db.query(StudioJob).filter(StudioJob.id == job_id, StudioJob.project_id == project_id).first()
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.project_id == project_id).first()
    if not job or not shot:
        raise HTTPException(status_code=404, detail="创作任务或分镜镜头不存在。")
    vid_abs = resolve_abs_path(job.output_file_path)
    if not vid_abs or not vid_abs.exists():
        raise HTTPException(status_code=400, detail="该创作任务尚未生成视频文件。")

    rel_vid, abs_vid = allocate_rel_path(project_id, "takes", "mp4", prefix=f"take_{shot_id}")
    shutil.copy2(vid_abs, abs_vid)
    dur, has_aud = probe_media_info(abs_vid)
    rel_thumb, abs_thumb = allocate_rel_path(project_id, "takes", "jpg", prefix=f"thumb_{shot_id}")
    thumb_ok = generate_thumbnail(abs_vid, abs_thumb, kind="video") is not None

    take = Take(
        shot_id=shot_id,
        project_id=project_id,
        engine="omni_flash",
        model_id=job.model,
        file_path=rel_vid,
        thumbnail_path=rel_thumb if thumb_ok else None,
        duration_sec=dur,
        resolution=job.resolution,
        has_audio=has_aud,
        prompt_used=job.enhanced_prompt or job.prompt,
        interaction_id=job.interaction_id,
        mode="generate",
        cost_usd=float(job.cost_usd or 0.0),
    )
    db.add(take)
    db.flush()
    shot.selected_take_id = take.id
    db.commit()
    db.refresh(take)
    return serialize_take(take)


@router.delete("/jobs/{job_id}")
def delete_studio_job(project_id: str, job_id: str, db: Session = Depends(get_db)):
    job = db.query(StudioJob).filter(StudioJob.id == job_id, StudioJob.project_id == project_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="创作任务不存在。")
    for rel in (job.output_file_path, job.output_thumb_path):
        try:
            abs_p = resolve_abs_path(rel)
            if abs_p and abs_p.exists():
                abs_p.unlink(missing_ok=True)
        except Exception:
            pass
    db.delete(job)
    db.commit()
    return {"deleted": True, "id": job_id}
