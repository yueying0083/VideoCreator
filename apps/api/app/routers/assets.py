from __future__ import annotations

import mimetypes
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import COST_RATES
from app.database import Asset, Project, SessionLocal, get_db
from app.schemas import (
    AssetCreate,
    AssetGenerateRequest,
    AssetOut,
    AssetUpdate,
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

    est_cost = COST_RATES["image"]
    job = create_job_record(
        project_id=project_id,
        kind="image",
        message=f"正在为资产「{asset.name}」生成定妆参考图...",
        estimated_cost_usd=est_cost,
    )

    prompt = (payload.prompt_override or "").strip() or (
        f"Create a clean, high-detail reference concept image for a {asset.kind} named '{asset.name}'. "
        f"Visual description: {asset.description or asset.name}. "
        f"Overall film visual style: {proj.style_prompt}. Clean studio framing, consistent lighting, no text watermark."
    )
    aspect = "1:1" if asset.kind in ("character", "prop") else proj.aspect_ratio

    def _worker(progress_cb):
        progress_cb(30, f"调用 Nano Banana 2.1 绘制「{asset.name}」定妆图...")
        rel_path, abs_path = allocate_rel_path(project_id, "assets", "png", prefix=f"gen_{asset_id}")
        _, model_used, is_demo = generate_image(
            prompt=prompt,
            output_path=abs_path,
            aspect_ratio=aspect,
            badge_title=f"{asset.name} ({asset.kind})",
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
        record_cost(project_id, job.id, "image", model_used, est_cost, is_demo, f"资产定妆: {asset.name}")
        return {"asset_id": asset_id, "file_url": to_media_url(rel_path), "is_demo": is_demo}

    submit_background_job(job.id, _worker)
    return _job_to_out(job)


@router.post("/{asset_id}/turnaround", response_model=JobTaskOut)
async def generate_asset_turnaround(project_id: str, asset_id: str, db: Session = Depends(get_db)):
    """Skill: Generate a 3-view character turnaround sheet (front/side/back) from the asset reference."""
    proj = db.get(Project, project_id)
    asset = db.query(Asset).filter(Asset.id == asset_id, Asset.project_id == project_id).first()
    if not proj or not asset:
        raise HTTPException(status_code=404, detail="项目或资产不存在")

    est_cost = COST_RATES["turnaround"]
    job = create_job_record(
        project_id=project_id,
        kind="turnaround",
        message=f"Skill：正在为「{asset.name}」生成角色三视图...",
        estimated_cost_usd=est_cost,
    )
    ref_abs = resolve_abs_path(asset.file_path)
    refs = [ref_abs] if (ref_abs and ref_abs.exists()) else []

    prompt = (
        f"Professional film character design turnaround sheet showing EXACTLY three full-body views side-by-side: "
        f"Front View, Side Profile View, and Back View of '{asset.name}'. "
        f"Strictly preserve the character identity, face, hair, clothing, colors, and proportions from the reference image. "
        f"Description: {asset.description}. Neutral studio backdrop, even lighting, style: {proj.style_prompt}."
    )

    def _worker(progress_cb):
        progress_cb(35, f"调用 Nano Banana 2.1 绘制「{asset.name}」正/侧/背三视图...")
        rel_path, abs_path = allocate_rel_path(project_id, "assets", "png", prefix=f"turnaround_{asset_id}")
        _, model_used, is_demo = generate_image(
            prompt=prompt,
            output_path=abs_path,
            aspect_ratio="16:9",
            reference_image_paths=refs,
            badge_title=f"{asset.name} · 3-View Turnaround",
        )
        session = SessionLocal()
        try:
            a = session.get(Asset, asset_id)
            if a:
                a.turnaround_path = rel_path
                session.commit()
        finally:
            session.close()
        record_cost(project_id, job.id, "turnaround", model_used, est_cost, is_demo, f"三视图 Skill: {asset.name}")
        return {"asset_id": asset_id, "turnaround_url": to_media_url(rel_path), "is_demo": is_demo}

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
