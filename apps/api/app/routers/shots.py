from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Literal
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import COST_RATES, estimate_video_cost, load_settings
from app.database import Asset, Project, SessionLocal, Shot, Take, get_db
from app.schemas import (
    BatchGenerateKeyframesRequest,
    BatchGenerateKeyframesResponse,
    BatchGenerateShotsRequest,
    IterateTakeRequest,
    JobTaskOut,
    KeyframeGenerateRequest,
    ShotCreate,
    ShotOut,
    ShotUpdate,
    TakeOut,
    VideoGenerateRequest,
)
from app.services.google_ai import generate_image, generate_video, review_video_qa
from app.services.media_renderer import extract_frame, extract_video_frame, probe_media_info
from app.services.omni_engine import MAX_REFERENCE_IMAGES
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
        resolution=getattr(t, "resolution", "720p") or "720p",
        has_audio=t.has_audio,
        prompt_used=t.prompt_used,
        interaction_id=getattr(t, "interaction_id", None),
        parent_take_id=getattr(t, "parent_take_id", None),
        mode=getattr(t, "mode", "generate") or "generate",
        qa_score=t.qa_score,
        qa_feedback=t.qa_feedback,
        qa_improved_prompt=getattr(t, "qa_improved_prompt", None),
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
        dialogue_mode=getattr(s, "dialogue_mode", "spoken") or "spoken",
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
        dialogue_mode=payload.dialogue_mode,
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


def _enqueue_shot_keyframe(
    proj: Project,
    shot: Shot,
    which: Literal["start", "end"],
    prompt_override: str | None = None,
    db: Session | None = None,
) -> JobTaskOut:
    try:
        asset_ids = json.loads(shot.asset_ids_json or "[]")
    except Exception:
        asset_ids = []

    assets: list[Asset] = []
    if asset_ids and db is not None:
        raw_assets = db.query(Asset).filter(Asset.id.in_(asset_ids)).all()
        by_id = {a.id: a for a in raw_assets}
        assets = [by_id[aid] for aid in asset_ids if aid in by_id]

    ref_paths: list[Path] = []
    asset_notes: list[str] = []
    text_only_notes: list[str] = []
    for a in assets:
        if (a.media_type or "image") != "image":
            continue
        rp = resolve_abs_path(a.file_path)
        if rp and rp.exists() and len(ref_paths) < MAX_REFERENCE_IMAGES:
            ref_paths.append(rp)
            asset_notes.append(f"Image {len(ref_paths)} [{a.kind}] {a.name}: {a.description}")
        else:
            text_only_notes.append(f"[{a.kind}] {a.name}: {a.description}")

    which_label = "首帧" if which == "start" else "尾帧"
    est_cost = COST_RATES["image"]
    project_id = proj.id
    shot_id = shot.id
    shot_title = shot.title
    aspect_ratio = proj.aspect_ratio

    job = create_job_record(
        project_id=project_id,
        shot_id=shot_id,
        kind="keyframe",
        message=f"正在合成「{shot_title}」{which_label}关键帧（融合 {len(ref_paths)} 个参考资产）...",
        estimated_cost_usd=est_cost,
    )

    frame_role = "exact opening start frame (t=0s)" if which == "start" else "closing end frame"
    all_notes = asset_notes + text_only_notes
    prompt = (prompt_override or "").strip() or (
        f"Cinematic film still depicting the {frame_role} of shot '{shot_title}'. "
        f"Shot framing: {shot.shot_type}, Camera: {shot.camera_movement}. "
        f"Scene visual: {shot.video_prompt_en or shot.visual_prompt_zh}. "
        f"Referenced visual assets to keep strictly consistent: {'; '.join(all_notes) if all_notes else 'N/A'}. "
        f"Attached reference images may contain studio portraits or reference sheets; extract only the character's identity/costume or environment architecture into ONE unified live-action/cinematic scene. "
        f"Global film style: {proj.style_prompt}. "
        f"STRICTLY ONE single full-bleed cinematic film frame, NO collage, NO grid, NO multi-panel comic layout, NO split screen, NO borders, NO turnaround sheet, NO text or subtitles."
    )

    def _worker(progress_cb):
        cfg = load_settings()
        provider_label = f"GPT ({cfg.openai_image_model})" if cfg.use_openai_for("keyframe") else "Nano Banana 2.1"
        progress_cb(30, f"调用 {provider_label} 合成{which_label}...")
        rel_path, abs_path = allocate_rel_path(project_id, "frames", "png", prefix=f"shot_{shot_id}_{which}")
        _, model_used, is_demo = generate_image(
            prompt=prompt,
            output_path=abs_path,
            aspect_ratio=aspect_ratio,
            reference_image_paths=ref_paths,
            badge_title=f"{shot_title} · {which_label}",
            purpose="keyframe",
            on_progress=progress_cb,
        )
        session = SessionLocal()
        try:
            s = session.get(Shot, shot_id)
            if s:
                if which == "start":
                    s.start_frame_path = rel_path
                else:
                    s.end_frame_path = rel_path
                session.commit()
        finally:
            session.close()
        record_cost(project_id, job.id, "keyframe", model_used, est_cost, is_demo, f"{shot_title} {which_label}")
        return {"shot_id": shot_id, "which": which, "url": to_media_url(rel_path), "is_demo": is_demo}

    submit_background_job(job.id, _worker, use_image_pool=True)
    return _job_to_out(job)


@router.post("/batch-keyframes", response_model=BatchGenerateKeyframesResponse)
async def batch_generate_keyframes(
    project_id: str,
    payload: BatchGenerateKeyframesRequest,
    db: Session = Depends(get_db),
):
    """Batch generate start or end keyframes for storyboard shots using the configured image engine."""
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    q = db.query(Shot).filter(Shot.project_id == project_id)
    if payload.episode_id:
        q = q.filter(Shot.episode_id == payload.episode_id)
    shots = q.order_by(Shot.order_index.asc(), Shot.created_at.asc()).all()

    tasks: list[JobTaskOut] = []
    skipped = 0
    for s in shots:
        existing_path = s.start_frame_path if payload.which == "start" else s.end_frame_path
        if existing_path and payload.only_missing:
            skipped += 1
            continue
        tasks.append(_enqueue_shot_keyframe(proj, s, payload.which, db=db))

    return BatchGenerateKeyframesResponse(
        submitted_count=len(tasks),
        skipped_count=skipped,
        tasks=tasks,
    )


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
    return _enqueue_shot_keyframe(proj, shot, payload.which, prompt_override=payload.prompt_override, db=db)


@router.delete("/{shot_id}/keyframe/{which}", response_model=ShotOut)
def clear_shot_keyframe(
    project_id: str,
    shot_id: str,
    which: Literal["start", "end"],
    db: Session = Depends(get_db),
):
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.project_id == project_id).first()
    if not shot:
        raise HTTPException(status_code=404, detail="镜头不存在")
    if which == "start":
        shot.start_frame_path = None
    else:
        shot.end_frame_path = None
    db.commit()
    db.refresh(shot)
    return serialize_shot(shot)


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


def _append_sentence(base: str, extra: str) -> str:
    clean = (base or "").strip()
    if not clean:
        return extra
    if clean[-1] in ".!?。！？\"”'’":
        return f"{clean} {extra}"
    return f"{clean}. {extra}"


def _compose_shot_prompt(shot: Shot, with_audio: bool, prompt_override_en: str | None = None) -> str:
    prompt_en = (prompt_override_en or "").strip() or (shot.video_prompt_en or "").strip() or (shot.visual_prompt_zh or "").strip()
    d_mode = (getattr(shot, "dialogue_mode", None) or "spoken").strip().lower()
    if with_audio:
        sfx = (shot.sfx_prompt or "").strip()
        if sfx and sfx.lower() not in prompt_en.lower():
            prompt_en = _append_sentence(prompt_en, f"Synchronized ambient SFX: {sfx}.")
        dialogue_txt = (shot.dialogue or "").strip()
        if d_mode == "spoken" and dialogue_txt:
            prompt_en = _append_sentence(prompt_en, f'Spoken dialogue: "{dialogue_txt}".')
        elif "no dialogue" not in prompt_en.lower() and "no spoken dialogue" not in prompt_en.lower():
            prompt_en = _append_sentence(prompt_en, "No spoken dialogue, no voiceover, no on-screen subtitles.")
    return prompt_en


def _execute_shot_video_sync(
    *,
    project_id: str,
    shot_id: str,
    task_id: str,
    engine: str,
    duration_sec: int,
    resolution: str,
    with_audio: bool,
    use_end_frame: bool,
    use_asset_refs_with_start_frame: bool = False,
    prompt_override_en: str | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Execute video generation for a single shot synchronously inside a worker thread."""
    session = SessionLocal()
    try:
        proj = session.get(Project, project_id)
        shot = session.query(Shot).filter(Shot.id == shot_id, Shot.project_id == project_id).first()
        if not proj or not shot:
            raise ValueError("项目或镜头不存在")

        start_abs = resolve_abs_path(shot.start_frame_path)
        end_abs = resolve_abs_path(shot.end_frame_path) if use_end_frame else None

        try:
            asset_ids = json.loads(shot.asset_ids_json or "[]")
        except Exception:
            asset_ids = []

        ref_paths: list[Path] = []
        ref_ids: list[str | None] = []
        ref_labels: list[str] = []
        if not start_abs or use_asset_refs_with_start_frame:
            max_refs = (MAX_REFERENCE_IMAGES - (1 if start_abs else 0) - (1 if end_abs else 0))
            if asset_ids and max_refs > 0:
                raw_assets = session.query(Asset).filter(Asset.id.in_(asset_ids)).all()
                by_id = {a.id: a for a in raw_assets}
                for aid in asset_ids:
                    a = by_id.get(aid)
                    if not a or (a.media_type or "image") != "image":
                        continue
                    rp = resolve_abs_path(a.file_path)
                    if rp and rp.exists():
                        ref_paths.append(rp)
                        ref_ids.append(a.id)
                        ref_labels.append(f"{a.kind} '{a.name}'")
                        if len(ref_paths) >= max_refs:
                            break

        prompt_en = _compose_shot_prompt(shot, with_audio, prompt_override_en)
        aspect_ratio = proj.aspect_ratio
        shot_title = shot.title
    finally:
        session.close()

    eff_duration = int(duration_sec)
    if engine == "omni_flash" and start_abs and end_abs and eff_duration > 10:
        eff_duration = 10

    mode = (
        "first_last_frame"
        if (start_abs and end_abs)
        else ("first_frame" if start_abs else ("reference_to_video" if ref_paths else "text_to_video"))
    )
    est_cost = estimate_video_cost(engine, eff_duration, resolution)

    rel_vid, abs_vid = allocate_rel_path(project_id, "takes", "mp4", prefix=f"take_{shot_id}")
    _, model_used, is_demo, interaction_id = generate_video(
        engine=engine,
        prompt_en=prompt_en,
        output_path=abs_vid,
        duration_sec=eff_duration,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        mode=mode,
        start_frame_path=start_abs,
        end_frame_path=end_abs,
        reference_image_paths=ref_paths,
        ref_image_asset_ids=ref_ids,
        ref_image_labels=ref_labels,
        with_audio=with_audio,
        badge_title=shot_title,
        on_progress=progress_cb,
    )

    if progress_cb:
        progress_cb(92, "提取封面缩略图与视频元信息...")
    dur, has_aud = probe_media_info(abs_vid)
    rel_thumb, abs_thumb = allocate_rel_path(project_id, "takes", "jpg", prefix=f"thumb_{shot_id}")
    thumb_ok = extract_frame(abs_vid, abs_thumb, at_end=False)

    session2 = SessionLocal()
    try:
        take = Take(
            shot_id=shot_id,
            project_id=project_id,
            engine=engine,
            model_id=model_used,
            file_path=rel_vid,
            thumbnail_path=rel_thumb if thumb_ok else None,
            duration_sec=dur,
            resolution=resolution,
            has_audio=has_aud,
            prompt_used=prompt_en,
            interaction_id=interaction_id,
            mode="generate",
            cost_usd=0.0 if is_demo else est_cost,
        )
        session2.add(take)
        session2.flush()
        s = session2.get(Shot, shot_id)
        if s:
            s.selected_take_id = take.id
        session2.commit()
        take_id = take.id
    finally:
        session2.close()

    record_cost(
        project_id,
        task_id,
        "video",
        model_used,
        est_cost,
        is_demo,
        f"{shot_title} ({engine}, {eff_duration}s {resolution})",
    )
    return {
        "shot_id": shot_id,
        "take_id": take_id,
        "file_url": to_media_url(rel_vid),
        "abs_vid": str(abs_vid),
        "is_demo": is_demo,
    }


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

    est_cost = estimate_video_cost(payload.engine, payload.duration_sec, payload.resolution)
    job = create_job_record(
        project_id=project_id,
        shot_id=shot_id,
        kind="video",
        message=f"正在使用 {payload.engine} 生成「{shot.title}」视频 ({payload.duration_sec}s · {payload.resolution})...",
        estimated_cost_usd=est_cost,
    )

    def _worker(progress_cb):
        res = _execute_shot_video_sync(
            project_id=project_id,
            shot_id=shot_id,
            task_id=job.id,
            engine=payload.engine,
            duration_sec=payload.duration_sec,
            resolution=payload.resolution,
            with_audio=payload.with_audio,
            use_end_frame=payload.use_end_frame,
            use_asset_refs_with_start_frame=payload.use_asset_refs_with_start_frame,
            prompt_override_en=payload.prompt_override_en,
            progress_cb=progress_cb,
        )
        return {k: v for k, v in res.items() if k != "abs_vid"}

    submit_background_job(job.id, _worker)
    return _job_to_out(job)


@router.post("/batch-generate")
async def batch_generate_shots(
    project_id: str,
    payload: BatchGenerateShotsRequest,
    db: Session = Depends(get_db),
):
    """Batch shoot storyboard shots in parallel or sequentially with automatic last-frame chaining."""
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    q = db.query(Shot).filter(Shot.project_id == project_id)
    if payload.episode_id:
        q = q.filter(Shot.episode_id == payload.episode_id)
    shots = q.order_by(Shot.order_index.asc(), Shot.created_at.asc()).all()

    target_shots = [s for s in shots if not (payload.only_pending and len(s.takes) > 0)]
    if not target_shots:
        return {"submitted_count": 0, "tasks": []}

    if not payload.chain_last_frame:
        created_tasks: list[JobTaskOut] = []
        for s in target_shots:
            est_cost = estimate_video_cost(payload.engine, s.duration_sec, payload.resolution)
            job = create_job_record(
                project_id=project_id,
                shot_id=s.id,
                kind="video",
                message=f"批量拍片排队中：{s.title} ({s.duration_sec}s · {payload.resolution})",
                estimated_cost_usd=est_cost,
            )

            def _make_worker(sid: str, dur: int, tid: str):
                def _w(progress_cb):
                    res = _execute_shot_video_sync(
                        project_id=project_id,
                        shot_id=sid,
                        task_id=tid,
                        engine=payload.engine,
                        duration_sec=dur,
                        resolution=payload.resolution,
                        with_audio=payload.with_audio,
                        use_end_frame=payload.use_end_frame,
                        use_asset_refs_with_start_frame=payload.use_asset_refs_with_start_frame,
                        progress_cb=progress_cb,
                    )
                    return {k: v for k, v in res.items() if k != "abs_vid"}

                return _w

            submit_background_job(job.id, _make_worker(s.id, s.duration_sec, job.id))
            created_tasks.append(_job_to_out(job))
        return {"submitted_count": len(created_tasks), "tasks": created_tasks}

    # Chained sequential execution: shot N's last frame -> shot N+1's start frame
    total_est = sum(estimate_video_cost(payload.engine, s.duration_sec, payload.resolution) for s in target_shots)
    shot_specs = [(s.id, s.title, int(s.duration_sec or 6)) for s in target_shots]
    chain_job = create_job_record(
        project_id=project_id,
        kind="batch_chain",
        message=f"尾帧接力批量拍片启动（共 {len(shot_specs)} 个镜头）...",
        estimated_cost_usd=round(total_est, 3),
    )

    def _chain_worker(progress_cb):
        total = len(shot_specs)
        completed_ids: list[str] = []
        for idx, (sid, stitle, sdur) in enumerate(shot_specs):
            base_pct = int((idx / total) * 85) + 5
            progress_cb(base_pct, f"尾帧接力 [{idx + 1}/{total}]：正在拍「{stitle}」...")

            def _sub_cb(_pct: int, msg: str, _idx: int = idx, _title: str = stitle) -> None:
                sub_p = int(((_idx + (_pct / 100.0)) / total) * 90) + 5
                progress_cb(min(95, sub_p), f"[{_idx + 1}/{total}] {_title}: {msg}")

            res = _execute_shot_video_sync(
                project_id=project_id,
                shot_id=sid,
                task_id=chain_job.id,
                engine=payload.engine,
                duration_sec=sdur,
                resolution=payload.resolution,
                with_audio=payload.with_audio,
                use_end_frame=payload.use_end_frame,
                use_asset_refs_with_start_frame=payload.use_asset_refs_with_start_frame,
                progress_cb=_sub_cb,
            )
            completed_ids.append(res["take_id"])

            if idx + 1 < total:
                next_sid = shot_specs[idx + 1][0]
                abs_vid = Path(res["abs_vid"])
                if abs_vid.exists():
                    frame_rel, frame_abs = allocate_rel_path(project_id, "frames", "png", prefix=f"chain_{next_sid}")
                    extract_video_frame(abs_vid, frame_abs, position="last")
                    s_next = SessionLocal()
                    try:
                        ns = s_next.get(Shot, next_sid)
                        if ns and not ns.start_frame_path:
                            ns.start_frame_path = frame_rel
                            s_next.commit()
                    finally:
                        s_next.close()

        return {"completed_takes": completed_ids, "count": len(completed_ids)}

    submit_background_job(chain_job.id, _chain_worker, use_chain_pool=True)
    return {"submitted_count": 1, "tasks": [_job_to_out(chain_job)]}


_NO_SPEECH_EDIT_RE = re.compile(
    r"no\s+(?:spoken\s+)?dialogue|without\s+speaking|no\s+voiceover|no\s+speech"
    r"|remove\s+(?:the\s+)?(?:voice|dialogue|speech)|无对白|不要说话|去掉旁白|去除旁白|去人声|闭嘴",
    re.IGNORECASE,
)


@router.post("/{shot_id}/takes/{take_id}/iterate", response_model=JobTaskOut)
async def iterate_shot_take(
    project_id: str,
    shot_id: str,
    take_id: str,
    payload: IterateTakeRequest,
    db: Session = Depends(get_db),
):
    """Multi-turn V2V Edit or Extend on an existing Take using Gemini Omni 1.2 Flash."""
    proj = db.get(Project, project_id)
    shot = db.query(Shot).filter(Shot.id == shot_id, Shot.project_id == project_id).first()
    take = db.query(Take).filter(Take.id == take_id, Take.shot_id == shot_id).first()
    if not proj or not shot or not take:
        raise HTTPException(status_code=404, detail="项目、镜头或 Take 不存在")

    if payload.action == "extend" and payload.duration_sec > 10:
        raise HTTPException(status_code=400, detail="单次视频续写时长上限为 10 秒。")

    cfg = load_settings()
    take_abs = resolve_abs_path(take.file_path)
    effective_strip_audio = bool(payload.strip_audio)
    if (
        payload.action == "edit"
        and not effective_strip_audio
        and take_abs
        and take_abs.exists()
        and _NO_SPEECH_EDIT_RE.search(payload.prompt)
    ):
        effective_strip_audio = True

    can_use_interaction = bool(
        take.interaction_id
        and not effective_strip_audio
        and (cfg.effective_mode == "demo" or not str(take.interaction_id).startswith("demo_"))
    )
    prev_iid = take.interaction_id if can_use_interaction else None
    source_vid = None if can_use_interaction else take_abs

    if not prev_iid and (not source_vid or not source_vid.exists()):
        raise HTTPException(status_code=404, detail="源 Take 视频文件不存在，无法发起改片或续写。")

    ref_imgs: list[Path] = []
    ref_ids: list[str | None] = []
    ref_labels: list[str] = []
    if payload.ref_asset_ids:
        assets = db.query(Asset).filter(Asset.id.in_(payload.ref_asset_ids[:6]), Asset.project_id == project_id).all()
        for a in assets:
            rp = resolve_abs_path(a.file_path)
            if rp and rp.exists() and (a.media_type or "image") == "image":
                ref_imgs.append(rp)
                ref_ids.append(a.id)
                ref_labels.append(f"{a.kind} '{a.name}'")

    est_cost = estimate_video_cost("omni_flash", payload.duration_sec, payload.resolution)
    action_label = "续写" if payload.action == "extend" else "多轮改片"
    job = create_job_record(
        project_id=project_id,
        shot_id=shot_id,
        kind="video",
        message=f"正在对「{shot.title}」发起 Omni {action_label} ({payload.duration_sec}s · {payload.resolution})...",
        estimated_cost_usd=est_cost,
    )
    aspect_ratio = proj.aspect_ratio

    def _worker(progress_cb):
        rel_vid, abs_vid = allocate_rel_path(project_id, "takes", "mp4", prefix=f"{payload.action}_{shot_id}")
        _, model_used, is_demo, new_iid = generate_video(
            engine="omni_flash",
            prompt_en=payload.prompt.strip(),
            output_path=abs_vid,
            duration_sec=payload.duration_sec,
            aspect_ratio=aspect_ratio,
            resolution=payload.resolution,
            mode=payload.action,
            source_video_path=source_vid,
            source_video_asset_id=None,
            reference_image_paths=ref_imgs,
            ref_image_asset_ids=ref_ids,
            ref_image_labels=ref_labels,
            with_audio=not effective_strip_audio,
            strip_audio=effective_strip_audio,
            previous_interaction_id=prev_iid,
            badge_title=f"{shot.title} · {action_label}",
            on_progress=progress_cb,
        )
        progress_cb(92, "提取缩略图与视频元信息...")
        dur, has_aud = probe_media_info(abs_vid)
        rel_thumb, abs_thumb = allocate_rel_path(project_id, "takes", "jpg", prefix=f"thumb_{shot_id}")
        thumb_ok = extract_frame(abs_vid, abs_thumb, at_end=False)

        session = SessionLocal()
        try:
            new_take = Take(
                shot_id=shot_id,
                project_id=project_id,
                engine="omni_flash",
                model_id=model_used,
                file_path=rel_vid,
                thumbnail_path=rel_thumb if thumb_ok else None,
                duration_sec=dur,
                resolution=payload.resolution,
                has_audio=has_aud,
                prompt_used=payload.prompt.strip(),
                interaction_id=new_iid,
                parent_take_id=take_id,
                mode=payload.action,
                cost_usd=0.0 if is_demo else est_cost,
            )
            session.add(new_take)
            session.flush()
            s = session.get(Shot, shot_id)
            if s:
                s.selected_take_id = new_take.id
            session.commit()
            new_take_id = new_take.id
        finally:
            session.close()

        record_cost(project_id, job.id, "video", model_used, est_cost, is_demo, f"{shot.title} ({action_label}, {payload.duration_sec}s)")
        return {"shot_id": shot_id, "take_id": new_take_id, "file_url": to_media_url(rel_vid), "is_demo": is_demo}

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
        resolution="1080p",
        has_audio=has_aud,
        prompt_used=f"Imported from external file: {file.filename}",
        mode="flow_import",
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
        message=f"Gemini 4 质检导演正在审看「{shot.title}」...",
        estimated_cost_usd=est_cost,
    )

    def _worker(progress_cb):
        progress_cb(40, "Gemini 4 多模态分析视频画面与连贯性...")
        qa_data, model_used, is_demo = review_video_qa(
            vid_abs,
            shot.title,
            shot.visual_prompt_zh,
            shot.video_prompt_en or shot.visual_prompt_zh,
        )
        score = int(qa_data.get("score", 7))
        summary = str(qa_data.get("summary", ""))
        issues = qa_data.get("issues") or []
        improved = str(qa_data.get("improved_prompt_en", "")).strip()
        feedback_text = summary
        if issues:
            feedback_text += "\n问题点：" + "；".join(str(x) for x in issues)

        session = SessionLocal()
        try:
            t = session.get(Take, take_id)
            if t:
                t.qa_score = max(1, min(10, score))
                t.qa_feedback = feedback_text
                t.qa_improved_prompt = improved or None
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
