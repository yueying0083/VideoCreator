from __future__ import annotations

import mimetypes
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import COST_RATES, load_settings
from app.database import Asset, Project, SessionLocal, get_db
from app.schemas import (
    AssetCreate,
    AssetGenerateRequest,
    AssetOut,
    AssetUpdate,
    BatchGenerateAssetsRequest,
    BatchGenerateAssetsResponse,
    ExtractFrameRequest,
    JobTaskOut,
    PrepAssetRequest,
)
from app.services.google_ai import generate_image
from app.services.media_renderer import (
    extract_video_frame,
    generate_thumbnail,
    inspect_media,
    prep_video_clip,
)
from app.services.storage import allocate_rel_path, resolve_abs_path, to_media_url
from app.services.task_runner import create_job_record, record_cost, submit_background_job

router = APIRouter(prefix="/api/projects/{project_id}/assets", tags=["assets"])

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def serialize_asset(a: Asset) -> AssetOut:
    return AssetOut(
        id=a.id,
        project_id=a.project_id,
        name=a.name,
        kind=a.kind,
        description=a.description,
        file_url=to_media_url(a.file_path),
        turnaround_url=to_media_url(a.turnaround_path),
        media_type=a.media_type or ("video" if a.kind == "video" else "image"),
        mime_type=a.mime_type or "",
        thumb_url=to_media_url(a.thumb_path),
        size_bytes=int(a.size_bytes or 0),
        width=a.width,
        height=a.height,
        duration_sec=a.duration_sec,
        fps=a.fps,
        has_audio=bool(a.has_audio),
        created_at=a.created_at,
    )


@router.get("", response_model=list[AssetOut])
def list_assets(project_id: str, db: Session = Depends(get_db)):
    assets = db.query(Asset).filter(Asset.project_id == project_id).order_by(Asset.created_at.asc()).all()
    return [serialize_asset(a) for a in assets]


@router.post("", response_model=AssetOut)
def create_asset(project_id: str, payload: AssetCreate, db: Session = Depends(get_db)):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    media_type = "video" if payload.kind == "video" else ("audio" if payload.kind == "audio" else "image")
    asset = Asset(
        project_id=project_id,
        name=payload.name.strip(),
        kind=payload.kind,
        description=payload.description.strip(),
        media_type=media_type,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return serialize_asset(asset)


@router.post("/upload-media", response_model=AssetOut)
async def upload_media_asset(
    project_id: str,
    file: UploadFile = File(...),
    kind: str | None = Form(default=None),
    name: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """Upload an image or video directly into the project Asset Hub with FFmpeg inspection & thumbnail."""
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    orig_name = file.filename or "upload"
    ext = Path(orig_name).suffix.lower()
    content_type = (file.content_type or "").lower()

    if ext in ALLOWED_IMAGE_EXTS or content_type.startswith("image/"):
        media_type = "image"
        ext = ext or ".png"
        mime_type = content_type if content_type.startswith("image/") else (mimetypes.guess_type(orig_name)[0] or "image/png")
        asset_kind = kind if kind in ("character", "scene", "prop") else "scene"
    elif ext in ALLOWED_VIDEO_EXTS or content_type.startswith("video/"):
        media_type = "video"
        ext = ext or ".mp4"
        mime_type = content_type if content_type.startswith("video/") else (mimetypes.guess_type(orig_name)[0] or "video/mp4")
        asset_kind = "video"
    else:
        raise HTTPException(
            status_code=400,
            detail="仅支持上传图片（PNG/JPG/WEBP）或视频（MP4/MOV/WEBM）素材。",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空。")
    if len(data) > 200 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="单个素材文件请控制在 200MB 以内。")

    rel_path, abs_path = allocate_rel_path(project_id, "assets", ext.lstrip("."), prefix=media_type)
    abs_path.write_bytes(data)

    meta = inspect_media(abs_path)
    thumb_rel, thumb_abs = allocate_rel_path(project_id, "thumbs", "jpg", prefix=f"asset_{media_type}")
    thumb_ok = generate_thumbnail(abs_path, thumb_abs, kind=media_type)

    asset = Asset(
        project_id=project_id,
        name=(name or Path(orig_name).stem or "上传素材").strip()[:120],
        kind=asset_kind,
        description=f"上传素材：{orig_name}",
        file_path=rel_path,
        media_type=media_type,
        mime_type=mime_type,
        thumb_path=thumb_rel if thumb_ok else None,
        size_bytes=int(meta.get("size_bytes") or len(data)),
        width=meta.get("width"),
        height=meta.get("height"),
        duration_sec=meta.get("duration_seconds") if media_type == "video" else None,
        fps=meta.get("fps") if media_type == "video" else None,
        has_audio=bool(media_type == "video" and meta.get("has_audio")),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return serialize_asset(asset)


@router.patch("/{asset_id}", response_model=AssetOut)
def update_asset(project_id: str, asset_id: str, payload: AssetUpdate, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(asset, k, v)
    db.commit()
    db.refresh(asset)
    return serialize_asset(asset)


@router.delete("/{asset_id}")
def delete_asset(project_id: str, asset_id: str, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    for rel in (asset.file_path, asset.turnaround_path, asset.thumb_path):
        try:
            abs_p = resolve_abs_path(rel)
            if abs_p and abs_p.exists():
                abs_p.unlink(missing_ok=True)
        except Exception:
            pass
    db.delete(asset)
    db.commit()
    return {"ok": True}


@router.post("/{asset_id}/upload", response_model=AssetOut)
async def upload_asset_file(
    project_id: str,
    asset_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    orig_name = file.filename or "asset.png"
    ext = Path(orig_name).suffix.lower() or ".png"
    content_type = (file.content_type or "").lower()
    is_vid = ext in ALLOWED_VIDEO_EXTS or content_type.startswith("video/")
    media_type = "video" if is_vid else "image"
    mime_type = content_type or (mimetypes.guess_type(orig_name)[0] or ("video/mp4" if is_vid else "image/png"))

    rel_path, abs_path = allocate_rel_path(project_id, "assets", ext.lstrip("."), prefix=f"asset_{asset.id}")
    content = await file.read()
    abs_path.write_bytes(content)

    meta = inspect_media(abs_path)
    thumb_rel, thumb_abs = allocate_rel_path(project_id, "thumbs", "jpg", prefix=f"thumb_{asset.id}")
    thumb_ok = generate_thumbnail(abs_path, thumb_abs, kind=media_type)

    asset.file_path = rel_path
    asset.media_type = media_type
    asset.mime_type = mime_type
    asset.thumb_path = thumb_rel if thumb_ok else None
    asset.size_bytes = int(meta.get("size_bytes") or len(content))
    asset.width = meta.get("width")
    asset.height = meta.get("height")
    asset.duration_sec = meta.get("duration_seconds") if is_vid else None
    asset.fps = meta.get("fps") if is_vid else None
    asset.has_audio = bool(is_vid and meta.get("has_audio"))
    asset.gemini_file_uri = None
    asset.gemini_file_expires_at = None
    db.commit()
    db.refresh(asset)
    return serialize_asset(asset)


@router.post("/{asset_id}/prep", response_model=AssetOut)
def prep_video_asset(
    project_id: str,
    asset_id: str,
    payload: PrepAssetRequest,
    db: Session = Depends(get_db),
):
    """Trim, scale, and optionally strip audio of a video asset via FFmpeg (ideal for 3s R2V or 10s editing)."""
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    if asset.media_type != "video" and asset.kind != "video":
        raise HTTPException(status_code=400, detail="仅支持对视频素材进行裁剪优化。")
    src_abs = resolve_abs_path(asset.file_path)
    if not src_abs or not src_abs.exists():
        raise HTTPException(status_code=404, detail="源视频文件不存在。")

    suffix_tag = f"{payload.duration}s" + ("_noaudio" if payload.strip_audio else "")
    rel_path, abs_path = allocate_rel_path(project_id, "assets", "mp4", prefix=f"prep_{asset_id}")
    try:
        meta = prep_video_clip(
            src_abs,
            abs_path,
            start_seconds=payload.start_seconds,
            duration=payload.duration,
            max_edge=payload.max_edge,
            strip_audio=payload.strip_audio,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    thumb_rel, thumb_abs = allocate_rel_path(project_id, "thumbs", "jpg", prefix=f"prep_{asset_id}")
    thumb_ok = generate_thumbnail(abs_path, thumb_abs, kind="video")

    new_asset = Asset(
        project_id=project_id,
        name=f"{asset.name}_{suffix_tag}"[:120],
        kind="video",
        description=f"FFmpeg 预处理自「{asset.name}」（{payload.duration}s" + ("，已剥离音轨" if payload.strip_audio else "") + "）",
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
    db.add(new_asset)
    db.commit()
    db.refresh(new_asset)
    return serialize_asset(new_asset)


@router.post("/{asset_id}/extract-frame", response_model=AssetOut)
def extract_frame_from_asset(
    project_id: str,
    asset_id: str,
    payload: ExtractFrameRequest,
    db: Session = Depends(get_db),
):
    """Extract first, last, or custom-timestamp PNG frame from a video asset into Asset Hub."""
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    if asset.media_type != "video" and asset.kind != "video":
        raise HTTPException(status_code=400, detail="仅支持从视频素材抽帧。")
    src_abs = resolve_abs_path(asset.file_path)
    if not src_abs or not src_abs.exists():
        raise HTTPException(status_code=404, detail="源视频文件不存在。")

    rel_path, abs_path = allocate_rel_path(project_id, "assets", "png", prefix=f"frame_{asset_id}")
    try:
        extract_video_frame(
            src_abs,
            abs_path,
            position=payload.position,
            timestamp_seconds=payload.timestamp_seconds,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    meta = inspect_media(abs_path)
    thumb_rel, thumb_abs = allocate_rel_path(project_id, "thumbs", "jpg", prefix=f"frame_{asset_id}")
    thumb_ok = generate_thumbnail(abs_path, thumb_abs, kind="image")
    label = {"first": "首帧", "last": "尾帧", "custom": f"{payload.timestamp_seconds or 0:.1f}s帧"}.get(
        payload.position, "关键帧"
    )

    new_asset = Asset(
        project_id=project_id,
        name=f"{asset.name}_{label}"[:120],
        kind="scene",
        description=f"从视频「{asset.name}」提取的{label}",
        file_path=rel_path,
        media_type="image",
        mime_type="image/png",
        thumb_path=thumb_rel if thumb_ok else None,
        size_bytes=int(meta.get("size_bytes") or abs_path.stat().st_size),
        width=meta.get("width"),
        height=meta.get("height"),
    )
    db.add(new_asset)
    db.commit()
    db.refresh(new_asset)
    return serialize_asset(new_asset)


def _build_portrait_prompt(proj: Project, asset: Asset, prompt_override: str | None = None) -> str:
    return (prompt_override or "").strip() or (
        f"Create a clean, high-detail reference concept image for a {asset.kind} named '{asset.name}'. "
        f"Visual description: {asset.description or asset.name}. "
        f"Overall film visual style: {proj.style_prompt}. Clean studio framing, consistent lighting, no text watermark."
    )


def _build_turnaround_prompt(proj: Project, asset: Asset) -> str:
    return (
        f"Professional film character design turnaround sheet showing EXACTLY three full-body views side-by-side: "
        f"Front View, Side Profile View, and Back View of '{asset.name}'. "
        f"Strictly preserve the character identity, face, hair, clothing, colors, and proportions from the reference image. "
        f"Description: {asset.description}. Neutral studio backdrop, even lighting, style: {proj.style_prompt}."
    )


def _run_asset_portrait(
    *,
    project_id: str,
    asset_id: str,
    asset_name: str,
    asset_kind: str,
    aspect: str,
    prompt: str,
    job_id: str,
    progress_cb,
) -> tuple[str, bool]:
    cfg = load_settings()
    provider_label = f"GPT ({cfg.openai_image_model})" if cfg.use_openai_for("asset") else "Nano Banana 2.1"
    progress_cb(30, f"调用 {provider_label} 绘制「{asset_name}」定妆图...")
    rel_path, abs_path = allocate_rel_path(project_id, "assets", "png", prefix=f"gen_{asset_id}")
    _, model_used, is_demo = generate_image(
        prompt=prompt,
        output_path=abs_path,
        aspect_ratio=aspect,
        badge_title=f"{asset_name} ({asset_kind})",
        purpose="asset",
        on_progress=progress_cb,
    )
    meta = inspect_media(abs_path)
    thumb_rel, thumb_abs = allocate_rel_path(project_id, "thumbs", "jpg", prefix=f"gen_{asset_id}")
    thumb_ok = generate_thumbnail(abs_path, thumb_abs, kind="image")

    session = SessionLocal()
    try:
        a = session.get(Asset, asset_id)
        if a:
            a.file_path = rel_path
            a.media_type = "image"
            a.mime_type = "image/png"
            a.thumb_path = thumb_rel if thumb_ok else None
            a.size_bytes = int(meta.get("size_bytes") or abs_path.stat().st_size)
            a.width = meta.get("width")
            a.height = meta.get("height")
            a.gemini_file_uri = None
            a.gemini_file_expires_at = None
            session.commit()
    finally:
        session.close()
    record_cost(project_id, job_id, "image", model_used, COST_RATES["image"], is_demo, f"资产定妆: {asset_name}")
    return rel_path, is_demo


def _run_asset_turnaround(
    *,
    project_id: str,
    asset_id: str,
    asset_name: str,
    prompt: str,
    ref_rel_path: str | None,
    job_id: str,
    progress_cb,
) -> tuple[str, bool]:
    cfg = load_settings()
    provider_label = f"GPT ({cfg.openai_image_model})" if cfg.use_openai_for("turnaround") else "Nano Banana 2.1"
    progress_cb(35, f"调用 {provider_label} 绘制「{asset_name}」正/侧/背三视图...")
    ref_abs = resolve_abs_path(ref_rel_path)
    refs = [ref_abs] if (ref_abs and ref_abs.exists()) else []
    rel_path, abs_path = allocate_rel_path(project_id, "assets", "png", prefix=f"turnaround_{asset_id}")
    _, model_used, is_demo = generate_image(
        prompt=prompt,
        output_path=abs_path,
        aspect_ratio="16:9",
        reference_image_paths=refs,
        badge_title=f"{asset_name} · 3-View Turnaround",
        purpose="turnaround",
        on_progress=progress_cb,
    )
    session = SessionLocal()
    try:
        a = session.get(Asset, asset_id)
        if a:
            a.turnaround_path = rel_path
            session.commit()
    finally:
        session.close()
    record_cost(project_id, job_id, "turnaround", model_used, COST_RATES["turnaround"], is_demo, f"三视图 Skill: {asset_name}")
    return rel_path, is_demo


def _enqueue_asset_portrait(proj: Project, asset: Asset, prompt_override: str | None = None) -> JobTaskOut:
    est_cost = COST_RATES["image"]
    job = create_job_record(
        project_id=proj.id,
        asset_id=asset.id,
        kind="image",
        message=f"正在为资产「{asset.name}」排队生成定妆照...",
        estimated_cost_usd=est_cost,
    )
    prompt = _build_portrait_prompt(proj, asset, prompt_override)
    aspect = "1:1" if asset.kind in ("character", "prop") else proj.aspect_ratio
    asset_id, asset_name, asset_kind, project_id = asset.id, asset.name, asset.kind, proj.id

    def _worker(progress_cb):
        rel_path, is_demo = _run_asset_portrait(
            project_id=project_id,
            asset_id=asset_id,
            asset_name=asset_name,
            asset_kind=asset_kind,
            aspect=aspect,
            prompt=prompt,
            job_id=job.id,
            progress_cb=progress_cb,
        )
        return {"asset_id": asset_id, "file_url": to_media_url(rel_path), "is_demo": is_demo}

    submit_background_job(job.id, _worker, use_image_pool=True)
    return _job_to_out(job)


def _enqueue_asset_turnaround(proj: Project, asset: Asset) -> JobTaskOut:
    est_cost = COST_RATES["turnaround"]
    job = create_job_record(
        project_id=proj.id,
        asset_id=asset.id,
        kind="turnaround",
        message=f"正在为「{asset.name}」排队生成角色三视图...",
        estimated_cost_usd=est_cost,
    )
    prompt = _build_turnaround_prompt(proj, asset)
    asset_id, asset_name, ref_rel, project_id = asset.id, asset.name, asset.file_path, proj.id

    def _worker(progress_cb):
        rel_path, is_demo = _run_asset_turnaround(
            project_id=project_id,
            asset_id=asset_id,
            asset_name=asset_name,
            prompt=prompt,
            ref_rel_path=ref_rel,
            job_id=job.id,
            progress_cb=progress_cb,
        )
        return {"asset_id": asset_id, "turnaround_url": to_media_url(rel_path), "is_demo": is_demo}

    submit_background_job(job.id, _worker, use_image_pool=True)
    return _job_to_out(job)


def _enqueue_asset_both(proj: Project, asset: Asset, *, regenerate: bool) -> JobTaskOut:
    need_portrait = regenerate or not asset.file_path
    need_turnaround = regenerate or not asset.turnaround_path
    est_cost = (COST_RATES["image"] if need_portrait else 0.0) + (
        COST_RATES["turnaround"] if need_turnaround else 0.0
    )
    job = create_job_record(
        project_id=proj.id,
        asset_id=asset.id,
        kind="turnaround",
        message=f"正在为「{asset.name}」排队生成定妆照 + 三视图...",
        estimated_cost_usd=est_cost,
    )
    portrait_prompt = _build_portrait_prompt(proj, asset)
    turnaround_prompt = _build_turnaround_prompt(proj, asset)
    aspect = "1:1" if asset.kind in ("character", "prop") else proj.aspect_ratio
    asset_id, asset_name, asset_kind, project_id = asset.id, asset.name, asset.kind, proj.id
    initial_file_path = asset.file_path

    def _worker(progress_cb):
        ref_rel = initial_file_path
        is_demo = False
        if need_portrait:
            ref_rel, is_demo = _run_asset_portrait(
                project_id=project_id,
                asset_id=asset_id,
                asset_name=asset_name,
                asset_kind=asset_kind,
                aspect=aspect,
                prompt=portrait_prompt,
                job_id=job.id,
                progress_cb=progress_cb,
            )
        turn_rel = None
        if need_turnaround:
            turn_rel, is_demo = _run_asset_turnaround(
                project_id=project_id,
                asset_id=asset_id,
                asset_name=asset_name,
                prompt=turnaround_prompt,
                ref_rel_path=ref_rel,
                job_id=job.id,
                progress_cb=progress_cb,
            )
        return {
            "asset_id": asset_id,
            "file_url": to_media_url(ref_rel),
            "turnaround_url": to_media_url(turn_rel),
            "is_demo": is_demo,
        }

    submit_background_job(job.id, _worker, use_image_pool=True)
    return _job_to_out(job)


@router.post("/batch-generate", response_model=BatchGenerateAssetsResponse)
def batch_generate_assets(
    project_id: str,
    payload: BatchGenerateAssetsRequest,
    db: Session = Depends(get_db),
):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    seen: set[str] = set()
    ordered_ids: list[str] = []
    for raw_id in payload.asset_ids:
        if raw_id and raw_id not in seen:
            seen.add(raw_id)
            ordered_ids.append(raw_id)

    rows = (
        db.query(Asset)
        .filter(Asset.project_id == project_id, Asset.id.in_(ordered_ids))
        .all()
    )
    by_id = {a.id: a for a in rows}

    tasks: list[JobTaskOut] = []
    skipped = 0
    for aid in ordered_ids:
        asset = by_id.get(aid)
        if not asset or asset.media_type == "video" or asset.kind == "video":
            skipped += 1
            continue

        if payload.target == "portrait":
            if asset.file_path and not payload.regenerate:
                skipped += 1
                continue
            tasks.append(_enqueue_asset_portrait(proj, asset))
        elif payload.target == "turnaround":
            if asset.turnaround_path and not payload.regenerate:
                skipped += 1
                continue
            tasks.append(_enqueue_asset_turnaround(proj, asset))
        else:
            if asset.file_path and asset.turnaround_path and not payload.regenerate:
                skipped += 1
                continue
            tasks.append(_enqueue_asset_both(proj, asset, regenerate=payload.regenerate))

    return BatchGenerateAssetsResponse(
        submitted_count=len(tasks),
        skipped_count=skipped,
        tasks=tasks,
    )


@router.post("/{asset_id}/generate", response_model=JobTaskOut)
async def generate_asset_image(
    project_id: str,
    asset_id: str,
    payload: AssetGenerateRequest,
    db: Session = Depends(get_db),
):
    proj = db.get(Project, project_id)
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
    if not proj or not asset:
        raise HTTPException(status_code=404, detail="项目或资产不存在")
    return _enqueue_asset_portrait(proj, asset, payload.prompt_override)


@router.post("/{asset_id}/turnaround", response_model=JobTaskOut)
async def generate_asset_turnaround(project_id: str, asset_id: str, db: Session = Depends(get_db)):
    """Skill: Generate a 3-view character turnaround sheet (front/side/back) from the asset reference."""
    proj = db.get(Project, project_id)
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
    if not proj or not asset:
        raise HTTPException(status_code=404, detail="项目或资产不存在")
    return _enqueue_asset_turnaround(proj, asset)


def _job_to_out(job) -> JobTaskOut:
    return JobTaskOut(
        id=job.id,
        project_id=job.project_id,
        shot_id=job.shot_id,
        asset_id=job.asset_id,
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
