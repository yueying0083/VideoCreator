from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import COST_RATES, estimate_video_cost
from app.database import Asset, Project, SessionLocal, Shot, Take, get_db
from app.schemas import (
    JobTaskOut,
    KeyframeGenerateRequest,
    ShotCreate,
    ShotOut,
    ShotUpdate,
    TakeOut,
    VideoGenerateRequest,
)
from app.services.google_ai import generate_image, generate_video, review_video_qa
from app.services.media_renderer import extract_frame, probe_media_info
from app.services.storage import allocate_rel_path, resolve_abs_path, to_media_url
from app.services.task_runner import create_job_record, record_cost, submit_background_job

router = APIRouter(prefix="/api/projects/{project_id}/shots", tags=["shots"])


def serialize_take(t: Take) -> TakeOut:
    return TakeOut(
        id=t.id,
        shot_id=t.shot_id,
        project_id=t.project_id,
        engine=t.engine,
        model_id=t.model_id,
        file_url=to_media_url(t.file_path) or "",
        thumbnail_url=to_media_url(t.thumbnail_path),
        duration_sec=t.duration_sec,
        has_audio=t.has_audio,
        prompt_used=t.prompt_used,
        qa_score=t.qa_score,
        qa_feedback=t.qa_feedback,
        cost_usd=t.cost_usd,
        created_at=t.created_at,
    )


def serialize_shot(s: Shot) -> ShotOut:
    try:
        asset_ids = json.loads(s.asset_ids_json or "[]")
    except Exception:
        asset_ids = []
    start_abs = resolve_abs_path(s.start_frame_path)
    end_abs = resolve_abs_path(s.end_frame_path)
    return ShotOut(
        id=s.id,
        project_id=s.project_id,
        episode_id=s.episode_id,
        order_index=s.order_index,
        title=s.title,
        shot_type=s.shot_type,
        camera_movement=s.camera_movement,
        visual_prompt_zh=s.visual_prompt_zh,
        video_prompt_en=s.video_prompt_en,
        dialogue=s.dialogue,
        sfx_prompt=s.sfx_prompt,
        duration_sec=s.duration_sec,
        asset_ids=asset_ids,
        start_frame_url=to_media_url(s.start_frame_path),
        end_frame_url=to_media_url(s.end_frame_path),
        start_frame_local_path=str(start_abs) if start_abs else None,
        end_frame_local_path=str(end_abs) if end_abs else None,
        selected_take_id=s.selected_take_id,
        trim_start=s.trim_start,
        trim_end=s.trim_end,
        takes=[serialize_take(t) for t in s.takes],
        created_at=s.created_at,
    )


@router.get("", response_model=list[ShotOut])
def list_shots(project_id: str, episode_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Shot).filter(Shot.project_id == project_id)
    if episode_id:
        q = q.filter(Shot.episode_id == episode_id)
    shots = q.order_by(Shot.order_index.asc(), Shot.created_at.asc()).all()
    return [serialize_shot(s) for s in shots]


@router.post("", response_model=ShotOut)
def create_shot(project_id: str, payload: ShotCreate, db: Session = Depends(get_db)):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    q = db.query(Shot).filter(Shot.project_id == project_id)
    if payload.episode_id:
        q = q.filter(Shot.episode_id == payload.episode_id)
    count = q.count()
    shot = Shot(
        project_id=project_id,
        episode_id=payload.episode_id,
        order_index=count,
        title=payload.title.strip() or f"镜头 {count + 1}",
        shot_type=payload.shot_type,
        camera_movement=payload.camera_movement,
        visual_prompt_zh=payload.visual_prompt_zh,
        video_prompt_en=payload.video_prompt_en,
        dialogue=payload.dialogue,
        sfx_prompt=payload.sfx_prompt,
        duration_sec=payload.duration_sec,
        asset_ids_json=json.dumps(payload.asset_ids),
    )
    db.add(shot)
    db.commit()
    db.refresh(shot)
    return serialize_shot(shot)


@router.patch("/{shot_id}", response_model=ShotOut)
def update_shot(project_id: str, shot_id: str, payload: ShotUpdate, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.project_id == project_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    data = payload.model_dump(exclude_none=True)
    if "asset_ids" in data:
        shot.asset_ids_json = json.dumps(data.pop("asset_ids"))
    for k, v in data.items():
        setattr(shot, k, v)
    db.commit()
    db.refresh(shot)
    return serialize_shot(shot)


@router.delete("/{shot_id}")
def delete_shot(project_id: str, shot_id: str, db: Session = Depends(get_db)):
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.project_id == project_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    db.delete(shot)
    db.commit()
    # Re-index remaining shots
    remaining = db.query(Shot).filter(Shot.project_id == project_id).order_by(Shot.order_index.asc()).all()
    for i, s in enumerate(remaining):
        s.order_index = i
    db.commit()
    return {"ok": True}


@router.post("/reorder")
def reorder_shots(project_id: str, shot_ids: list[str], db: Session = Depends(get_db)):
    shots = db.query(Shot).filter(Shot.project_id == project_id).all()
    shot_map = {s.id: s for s in shots}
    for idx, sid in enumerate(shot_ids):
        if sid in shot_map:
            shot_map[sid].order_index = idx
    db.commit()
    return {"ok": True}


@router.post("/{shot_id}/keyframe/generate", response_model=JobTaskOut)
async def generate_shot_keyframe(
    project_id: str,
    shot_id: str,
    payload: KeyframeGenerateRequest,
    db: Session = Depends(get_db),
):
    proj = db.get(Project, project_id)
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.project_id == project_id).first()
    if not proj or not shot:
        raise HTTPException(status_code=404, detail="项目或镜头不存在")

    try:
        asset_ids = json.loads(shot.asset_ids_json or "[]")
    except Exception:
        asset_ids = []
    assets = db.query(Asset).filter(Asset.id.in_(asset_ids)).all() if asset_ids else []
    ref_paths: list[Path] = []
    asset_notes: list[str] = []
    for a in assets:
        asset_notes.append(f"[{a.kind}] {a.name}: {a.description}")
        rp = resolve_abs_path(a.file_path)
        if rp and rp.exists():
            ref_paths.append(rp)

    which_label = "首帧" if payload.which == "start" else "尾帧"
    est_cost = COST_RATES["image"]
    job = create_job_record(
        project_id=project_id,
        shot_id=shot_id,
        kind="keyframe",
        message=f"正在合成「{shot.title}」{which_label}关键帧（融合 {len(ref_paths)} 个参考资产）...",
        estimated_cost_usd=est_cost,
    )

    frame_role = "opening start frame" if payload.which == "start" else "closing end frame"
    prompt = (payload.prompt_override or "").strip() or (
        f"Cinematic film still for the {frame_role} of shot '{shot.title}'. "
        f"Shot framing: {shot.shot_type}, Camera: {shot.camera_movement}. "
        f"Scene description: {shot.video_prompt_en or shot.visual_prompt_zh}. "
        f"Referenced visual assets to keep strictly consistent: {'; '.join(asset_notes) if asset_notes else 'N/A'}. "
        f"Global film style: {proj.style_prompt}. Single full-bleed film frame, no split screen, no text overlay."
    )

    def _worker(progress_cb):
        progress_cb(30, f"调用 Nano Banana 2 合成{which_label}...")
        rel_path, abs_path = allocate_rel_path(project_id, "frames", "png", prefix=f"shot_{shot_id}_{payload.which}")
        _, model_used, is_demo = generate_image(
            prompt=prompt,
            output_path=abs_path,
            aspect_ratio=proj.aspect_ratio,
            reference_image_paths=ref_paths,
            badge_title=f"{shot.title} · {which_label}",
        )
        session = SessionLocal()
        try:
            s = session.get(Shot, shot_id)
            if s:
                if payload.which == "start":
                    s.start_frame_path = rel_path
                else:
                    s.end_frame_path = rel_path
                session.commit()
        finally:
            session.close()
        record_cost(project_id, job.id, "keyframe", model_used, est_cost, is_demo, f"{shot.title} {which_label}")
        return {"shot_id": shot_id, "which": payload.which, "url": to_media_url(rel_path), "is_demo": is_demo}

    submit_background_job(job.id, _worker)
    return _job_to_out(job)


@router.post("/{shot_id}/keyframe/from-prev-end", response_model=ShotOut)
def copy_prev_shot_last_frame(project_id: str, shot_id: str, db: Session = Depends(get_db)):
    """Continuity Skill: Extract the final frame of the previous shot's selected take as this shot's start frame."""
    shots = (
        db.query(Shot)
        .filter(Shot.project_id == project_id)
        .order_by(Shot.order_index.asc(), Shot.created_at.asc())
        .all()
    )
    idx = next((i for i, s in enumerate(shots) if s.id == shot_id), -1)
    if idx <= 0:
        raise HTTPException(status_code=400, detail="没有上一个镜头可供提取尾帧")

    prev_shot = shots[idx - 1]
    curr_shot = shots[idx]

    take = None
    if prev_shot.selected_take_id:
        take = db.get(Take, prev_shot.selected_take_id)
    if not take and prev_shot.takes:
        take = prev_shot.takes[0]

    if take:
        take_abs = resolve_abs_path(take.file_path)
        if not take_abs or not take_abs.exists():
            raise HTTPException(status_code=404, detail="上一镜头的视频文件不存在")
        rel_path, abs_path = allocate_rel_path(project_id, "frames", "png", prefix=f"cont_{shot_id}")
        ok = extract_frame(take_abs, abs_path, at_end=True)
        if not ok:
            raise HTTPException(status_code=500, detail="FFmpeg 提取尾帧失败")
        curr_shot.start_frame_path = rel_path
    elif prev_shot.end_frame_path:
        curr_shot.start_frame_path = prev_shot.end_frame_path
    else:
        raise HTTPException(status_code=400, detail="上一镜头尚未生成视频或尾帧图")

    db.commit()
    db.refresh(curr_shot)
    return serialize_shot(curr_shot)


@router.post("/{shot_id}/video/generate", response_model=JobTaskOut)
async def generate_shot_video(
    project_id: str,
    shot_id: str,
    payload: VideoGenerateRequest,
    db: Session = Depends(get_db),
):
    proj = db.get(Project, project_id)
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.project_id == project_id).first()
    if not proj or not shot:
        raise HTTPException(status_code=404, detail="项目或镜头不存在")

    est_cost = estimate_video_cost(payload.engine, payload.duration_sec)
    job = create_job_record(
        project_id=project_id,
        shot_id=shot_id,
        kind="video",
        message=f"正在使用 {payload.engine} 生成「{shot.title}」视频 ({payload.duration_sec}s)...",
        estimated_cost_usd=est_cost,
    )

    try:
        asset_ids = json.loads(shot.asset_ids_json or "[]")
    except Exception:
        asset_ids = []
    assets = db.query(Asset).filter(Asset.id.in_(asset_ids)).all() if asset_ids else []
    ref_paths = [rp for a in assets if (rp := resolve_abs_path(a.file_path)) and rp.exists()]

    start_abs = resolve_abs_path(shot.start_frame_path)
    end_abs = resolve_abs_path(shot.end_frame_path) if payload.use_end_frame else None

    prompt_en = (payload.prompt_override_en or "").strip() or shot.video_prompt_en or shot.visual_prompt_zh
    if payload.with_audio and shot.sfx_prompt and shot.sfx_prompt.lower() not in prompt_en.lower():
        prompt_en = f"{prompt_en}. Synchronized audio & SFX: {shot.sfx_prompt}."
    if payload.with_audio and shot.dialogue:
        prompt_en = f'{prompt_en} Spoken dialogue: "{shot.dialogue}".'

    def _worker(progress_cb):
        rel_vid, abs_vid = allocate_rel_path(project_id, "takes", "mp4", prefix=f"take_{shot_id}")
        _, model_used, is_demo = generate_video(
            engine=payload.engine,
            prompt_en=prompt_en,
            output_path=abs_vid,
            duration_sec=payload.duration_sec,
            aspect_ratio=proj.aspect_ratio,
            start_frame_path=start_abs,
            end_frame_path=end_abs,
            reference_image_paths=ref_paths,
            with_audio=payload.with_audio,
            badge_title=shot.title,
            on_progress=progress_cb,
        )
        progress_cb(92, "提取封面缩略图与视频元信息...")
        dur, has_aud = probe_media_info(abs_vid)
        rel_thumb, abs_thumb = allocate_rel_path(project_id, "takes", "jpg", prefix=f"thumb_{shot_id}")
        thumb_ok = extract_frame(abs_vid, abs_thumb, at_end=False)

        session = SessionLocal()
        try:
            take = Take(
                shot_id=shot_id,
                project_id=project_id,
                engine=payload.engine,
                model_id=model_used,
                file_path=rel_vid,
                thumbnail_path=rel_thumb if thumb_ok else None,
                duration_sec=dur,
                has_audio=has_aud,
                prompt_used=prompt_en,
                cost_usd=0.0 if is_demo else est_cost,
            )
            session.add(take)
            session.flush()
            s = session.get(Shot, shot_id)
            if s:
                s.selected_take_id = take.id
            session.commit()
            take_id = take.id
        finally:
            session.close()

        record_cost(project_id, job.id, "video", model_used, est_cost, is_demo, f"{shot.title} ({payload.engine}, {payload.duration_sec}s)")
        return {"shot_id": shot_id, "take_id": take_id, "file_url": to_media_url(rel_vid), "is_demo": is_demo}

    submit_background_job(job.id, _worker)
    return _job_to_out(job)


@router.post("/{shot_id}/takes/import", response_model=TakeOut)
async def import_external_take(
    project_id: str,
    shot_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Google Flow Bridge: Import an externally generated MP4 (e.g., from Google Flow 25,000 Ultra credits) as a Take."""
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.project_id == project_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")

    ext = Path(file.filename or "clip.mp4").suffix.lstrip(".") or "mp4"
    rel_vid, abs_vid = allocate_rel_path(project_id, "takes", ext, prefix=f"flow_{shot_id}")
    abs_vid.write_bytes(await file.read())

    dur, has_aud = probe_media_info(abs_vid)
    rel_thumb, abs_thumb = allocate_rel_path(project_id, "takes", "jpg", prefix=f"thumb_{shot_id}")
    thumb_ok = extract_frame(abs_vid, abs_thumb, at_end=False)

    take = Take(
        shot_id=shot_id,
        project_id=project_id,
        engine="flow_import",
        model_id="google-flow-external",
        file_path=rel_vid,
        thumbnail_path=rel_thumb if thumb_ok else None,
        duration_sec=dur,
        has_audio=has_aud,
        prompt_used=f"Imported from external file: {file.filename}",
        cost_usd=0.0,
    )
    db.add(take)
    db.flush()
    shot.selected_take_id = take.id
    db.commit()
    db.refresh(take)
    return serialize_take(take)


@router.post("/{shot_id}/takes/{take_id}/qa", response_model=JobTaskOut)
async def run_take_qa_review(
    project_id: str,
    shot_id: str,
    take_id: str,
    db: Session = Depends(get_db),
):
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.project_id == project_id).first()
    take = db.query(Take).filter(Take.id == take_id, Take.shot_id == shot_id).first()
    if not shot or not take:
        raise HTTPException(status_code=404, detail="镜头或 Take 不存在")
    vid_abs = resolve_abs_path(take.file_path)
    if not vid_abs or not vid_abs.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    est_cost = COST_RATES["qa"]
    job = create_job_record(
        project_id=project_id,
        shot_id=shot_id,
        kind="qa",
        message=f"Gemini 质检导演正在审看「{shot.title}」...",
        estimated_cost_usd=est_cost,
    )

    def _worker(progress_cb):
        progress_cb(40, "Gemini 多模态分析视频画面与连贯性...")
        qa_data, model_used, is_demo = review_video_qa(
            vid_abs,
            shot.title,
            shot.visual_prompt_zh,
            shot.video_prompt_en or shot.visual_prompt_zh,
        )
        score = int(qa_data.get("score", 7))
        summary = str(qa_data.get("summary", ""))
        issues = qa_data.get("issues") or []
        improved = str(qa_data.get("improved_prompt_en", ""))
        feedback_text = summary
        if issues:
            feedback_text += "\n问题点：" + "；".join(str(x) for x in issues)
        if improved:
            feedback_text += f"\n优化建议 Prompt：{improved}"

        session = SessionLocal()
        try:
            t = session.get(Take, take_id)
            if t:
                t.qa_score = max(1, min(10, score))
                t.qa_feedback = feedback_text
                session.commit()
        finally:
            session.close()
        record_cost(project_id, job.id, "qa", model_used, est_cost, is_demo, f"自动审片: {shot.title}")
        return {"take_id": take_id, "qa_score": score, "qa_feedback": feedback_text, "improved_prompt_en": improved}

    submit_background_job(job.id, _worker)
    return _job_to_out(job)


def _job_to_out(job) -> JobTaskOut:
    return JobTaskOut(
        id=job.id,
        project_id=job.project_id,
        shot_id=job.shot_id,
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
