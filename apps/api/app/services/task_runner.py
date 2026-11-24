from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from app.database import CostLog, JobTask, SessionLocal, utcnow


def create_job_record(
    project_id: str,
    kind: str,
    message: str = "任务已入队...",
    shot_id: str | None = None,
    estimated_cost_usd: float = 0.0,
) -> JobTask:
    db = SessionLocal()
    try:
        job = JobTask(
            project_id=project_id,
            shot_id=shot_id,
            kind=kind,
            status="queued",
            progress=5,
            message=message,
            estimated_cost_usd=estimated_cost_usd,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    finally:
        db.close()


def update_job_record(
    task_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    db = SessionLocal()
    try:
        job = db.get(JobTask, task_id)
        if not job:
            return
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = max(0, min(100, int(progress)))
        if message is not None:
            job.message = message
        if result is not None:
            job.result_json = json.dumps(result, ensure_ascii=False)
        if error is not None:
            job.error = error
        job.updated_at = utcnow()
        db.commit()
    finally:
        db.close()


def record_cost(
    project_id: str | None,
    task_id: str | None,
    category: str,
    model_id: str,
    cost_usd: float,
    is_demo: bool,
    note: str = "",
) -> None:
    db = SessionLocal()
    try:
        entry = CostLog(
            project_id=project_id,
            task_id=task_id,
            category=category,
            model_id=model_id,
            cost_usd=round(float(cost_usd), 4),
            is_demo=is_demo,
            note=note[:290],
        )
        db.add(entry)
        db.commit()
    finally:
        db.close()


def submit_background_job(
    task_id: str,
    worker_fn: Callable[[Callable[[int, str], None]], dict[str, Any]],
) -> None:
    """Schedule a blocking media/AI worker in a thread pool and update SQLite JobTask state."""

    def _progress_cb(pct: int, msg: str) -> None:
        update_job_record(task_id, status="running", progress=pct, message=msg)

    async def _runner() -> None:
        update_job_record(task_id, status="running", progress=10, message="正在执行...")
        try:
            result = await asyncio.to_thread(worker_fn, _progress_cb)
            update_job_record(
                task_id,
                status="completed",
                progress=100,
                message="任务已完成",
                result=result,
            )
        except Exception as exc:
            update_job_record(
                task_id,
                status="failed",
                progress=100,
                message="任务执行失败",
                error=str(exc),
            )

    loop = asyncio.get_running_loop()
    loop.create_task(_runner())


def mark_stale_jobs_on_startup() -> None:
    """If server restarted mid-job, cleanly mark orphaned running/queued jobs as failed."""
    db = SessionLocal()
    try:
        stale = db.query(JobTask).filter(JobTask.status.in_(["queued", "running"])).all()
        for job in stale:
            job.status = "failed"
            job.error = "服务重启中断了上次任务，请重新触发"
            job.message = "已中断"
            job.updated_at = utcnow()
        if stale:
            db.commit()
    finally:
        db.close()
