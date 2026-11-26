from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncIterator, Callable

from app.config import load_settings
from app.database import CostLog, JobTask, SessionLocal, StudioJob, utcnow
from app.services.genai_utils import sanitize_error

_cfg = load_settings()
_worker_pool = ThreadPoolExecutor(max_workers=_cfg.max_concurrent_jobs, thread_name_prefix="vc-worker")
_image_pool = ThreadPoolExecutor(max_workers=12, thread_name_prefix="vc-img")
_chain_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vc-chain")


class DynamicConcurrencyLimiter:
    """Thread-safe FIFO semaphore whose concurrency cap follows runtime settings."""

    def __init__(self, limit_getter: Callable[[], int]) -> None:
        self._cond = threading.Condition()
        self._limit_getter = limit_getter
        self._in_flight = 0
        self._waiting: list[int] = []
        self._seq = 0

    def notify_all(self) -> None:
        with self._cond:
            self._cond.notify_all()

    @contextmanager
    def acquire(self, on_wait: Callable[[int, int], None] | None = None):
        with self._cond:
            self._seq += 1
            ticket = self._seq
            self._waiting.append(ticket)
            notified_wait = False
            try:
                while True:
                    limit = max(1, int(self._limit_getter()))
                    is_next = bool(self._waiting) and self._waiting[0] == ticket
                    if is_next and self._in_flight < limit:
                        self._waiting.pop(0)
                        self._in_flight += 1
                        self._cond.notify_all()
                        break
                    pos = self._waiting.index(ticket) + 1
                    if not notified_wait and on_wait:
                        notified_wait = True
                        on_wait(limit, pos)
                    self._cond.wait(timeout=1.0)
            except BaseException:
                if ticket in self._waiting:
                    self._waiting.remove(ticket)
                    self._cond.notify_all()
                raise

        try:
            yield
        finally:
            with self._cond:
                self._in_flight = max(0, self._in_flight - 1)
                self._cond.notify_all()


openai_image_limiter = DynamicConcurrencyLimiter(lambda: load_settings().openai_max_concurrent)


def notify_openai_concurrency_changed() -> None:
    openai_image_limiter.notify_all()

_event_loop: asyncio.AbstractEventLoop | None = None
_subscribers: set[asyncio.Queue[str]] = set()
_sub_lock = threading.Lock()


def attach_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _event_loop
    _event_loop = loop


def publish_event(event_type: str, data: dict[str, Any]) -> None:
    payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False, default=str)
    with _sub_lock:
        subs = list(_subscribers)
    if not subs or not _event_loop:
        return
    for q in subs:
        try:
            _event_loop.call_soon_threadsafe(q.put_nowait, payload)
        except Exception:
            pass


async def subscribe_events() -> AsyncIterator[str]:
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=300)
    with _sub_lock:
        _subscribers.add(q)
    try:
        yield f"data: {json.dumps({'type': 'connected', 'data': {}})}\n\n"
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=20.0)
                yield f"data: {msg}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        with _sub_lock:
            _subscribers.discard(q)


def _serialize_job_task(j: JobTask) -> dict[str, Any]:
    res = None
    if j.result_json:
        try:
            res = json.loads(j.result_json)
        except Exception:
            res = None
    return {
        "id": j.id,
        "project_id": j.project_id,
        "shot_id": j.shot_id,
        "asset_id": j.asset_id,
        "kind": j.kind,
        "status": j.status,
        "progress": j.progress,
        "message": j.message,
        "result": res,
        "error": j.error,
        "estimated_cost_usd": j.estimated_cost_usd,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "updated_at": j.updated_at.isoformat() if j.updated_at else None,
    }


def create_job_record(
    project_id: str,
    kind: str,
    message: str = "任务已入队...",
    shot_id: str | None = None,
    asset_id: str | None = None,
    estimated_cost_usd: float = 0.0,
) -> JobTask:
    db = SessionLocal()
    try:
        job = JobTask(
            project_id=project_id,
            shot_id=shot_id,
            asset_id=asset_id,
            kind=kind,
            status="queued",
            progress=5,
            message=message,
            estimated_cost_usd=estimated_cost_usd,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        publish_event("task_update", _serialize_job_task(job))
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
        db.refresh(job)
        publish_event("task_update", _serialize_job_task(job))
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
    *,
    use_chain_pool: bool = False,
    use_image_pool: bool = False,
) -> None:
    """Schedule a blocking media/AI worker in a bounded thread pool and update SQLite JobTask state."""

    def _progress_cb(pct: int, msg: str) -> None:
        update_job_record(task_id, status="running", progress=pct, message=msg)

    def _run_sync() -> None:
        update_job_record(task_id, status="running", progress=10, message="正在执行...")
        try:
            result = worker_fn(_progress_cb)
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
                error=sanitize_error(exc),
            )

    pool = _chain_pool if use_chain_pool else (_image_pool if use_image_pool else _worker_pool)
    pool.submit(_run_sync)


def submit_studio_worker(fn: Callable[[], None]) -> None:
    _worker_pool.submit(fn)


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

        stale_studio = (
            db.query(StudioJob)
            .filter(StudioJob.status.in_(["queued", "uploading", "generating", "downloading"]))
            .all()
        )
        for sj in stale_studio:
            sj.status = "failed"
            sj.error_message = "任务在后端重启时中断，请重新发起生成。"
            sj.progress_message = "已中断"
            sj.updated_at = utcnow()

        if stale or stale_studio:
            db.commit()
    finally:
        db.close()
