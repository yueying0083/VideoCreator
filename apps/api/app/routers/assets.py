from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import COST_RATES
from app.database import Asset, Project, SessionLocal, get_db
from app.schemas import AssetCreate, AssetGenerateRequest, AssetOut, AssetUpdate, JobTaskOut
from app.services.google_ai import generate_image
from app.services.storage import allocate_rel_path, resolve_abs_path, to_media_url
from app.services.task_runner import create_job_record, record_cost, submit_background_job

router = APIRouter(prefix="/api/projects/{project_id}/assets", tags=["assets"])


def serialize_asset(a: Asset) -> AssetOut:
    return AssetOut(
        id=a.id,
        project_id=a.project_id,
        name=a.name,
        kind=a.kind,
        description=a.description,
        file_url=to_media_url(a.file_path),
        turnaround_url=to_media_url(a.turnaround_path),
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
    asset = Asset(
        project_id=project_id,
        name=payload.name.strip(),
        kind=payload.kind,
        description=payload.description.strip(),
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
    ext = Path(file.filename or "asset.png").suffix.lstrip(".") or "png"
    rel_path, abs_path = allocate_rel_path(project_id, "assets", ext, prefix=f"asset_{asset.id}")
    content = await file.read()
    abs_path.write_bytes(content)
    asset.file_path = rel_path
    db.commit()
    db.refresh(asset)
    return serialize_asset(asset)


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
        progress_cb(30, f"调用 Nano Banana 2 绘制「{asset.name}」定妆图...")
        rel_path, abs_path = allocate_rel_path(project_id, "assets", "png", prefix=f"gen_{asset_id}")
        _, model_used, is_demo = generate_image(
            prompt=prompt,
            output_path=abs_path,
            aspect_ratio=aspect,
            badge_title=f"{asset.name} ({asset.kind})",
        )
        session = SessionLocal()
        try:
            a = session.get(Asset, asset_id)
            if a:
                a.file_path = rel_path
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
        progress_cb(35, f"调用 Nano Banana 2 绘制「{asset.name}」正/侧/背三视图...")
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
