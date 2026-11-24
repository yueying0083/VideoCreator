from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import Project, get_db
from app.schemas import ProjectCreate, ProjectOut, ProjectUpdate
from app.services.storage import delete_project_files, ensure_project_dirs, to_media_url

router = APIRouter(prefix="/api/projects", tags=["projects"])


def serialize_project(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        name=p.name,
        description=p.description,
        aspect_ratio=p.aspect_ratio,
        style_prompt=p.style_prompt,
        bgm_url=to_media_url(p.bgm_path),
        bgm_prompt=p.bgm_prompt,
        bgm_volume=p.bgm_volume,
        subtitle_srt=p.subtitle_srt,
        novel_title=p.novel_title or "",
        shot_count=len(p.shots),
        asset_count=len(p.assets),
        episode_count=len(p.episodes),
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.updated_at.desc()).all()
    return [serialize_project(p) for p in projects]


@router.post("", response_model=ProjectOut)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    proj = Project(
        name=payload.name.strip(),
        description=payload.description.strip(),
        aspect_ratio=payload.aspect_ratio,
        style_prompt=payload.style_prompt.strip(),
    )
    db.add(proj)
    db.commit()
    db.refresh(proj)
    ensure_project_dirs(proj.id)
    return serialize_project(proj)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    return serialize_project(proj)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db)):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(proj, field, value)
    db.commit()
    db.refresh(proj)
    return serialize_project(proj)


@router.delete("/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    db.delete(proj)
    db.commit()
    delete_project_files(project_id)
    return {"ok": True}
