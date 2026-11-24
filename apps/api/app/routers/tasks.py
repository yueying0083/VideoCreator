from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import JobTask, get_db
from app.schemas import JobTaskOut

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def serialize_job(j: JobTask) -> JobTaskOut:
    res = None
    if j.result_json:
        try:
            res = json.loads(j.result_json)
        except Exception:
            res = None
    return JobTaskOut(
        id=j.id,
        project_id=j.project_id,
        shot_id=j.shot_id,
        kind=j.kind,
        status=j.status,
        progress=j.progress,
        message=j.message,
        result=res,
        error=j.error,
        estimated_cost_usd=j.estimated_cost_usd,
        created_at=j.created_at,
        updated_at=j.updated_at,
    )


@router.get("", response_model=list[JobTaskOut])
def list_tasks(project_id: str | None = None, limit: int = 30, db: Session = Depends(get_db)):
    q = db.query(JobTask)
    if project_id:
        q = q.filter(JobTask.project_id == project_id)
    rows = q.order_by(JobTask.created_at.desc()).limit(limit).all()
    return [serialize_job(r) for r in rows]


@router.get("/{task_id}", response_model=JobTaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)):
    job = db.get(JobTask, task_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return serialize_job(job)
