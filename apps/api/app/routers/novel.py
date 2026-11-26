from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import COST_RATES
from app.database import Asset, Episode, Project, SessionLocal, Shot, get_db
from app.schemas import (
    EpisodeBreakdownRequest,
    EpisodeOut,
    EpisodeUpdate,
    ExtractBibleRequest,
    JobTaskOut,
    NovelImportTextRequest,
)
from app.services.novel_splitter import (
    breakdown_episode_to_shots,
    extract_book_bible,
    extract_novel_text_from_file,
    split_novel_into_episodes,
)
from app.services.task_runner import create_job_record, record_cost, submit_background_job

router = APIRouter(prefix="/api/projects/{project_id}/novel", tags=["novel"])


def serialize_episode(ep: Episode) -> EpisodeOut:
    return EpisodeOut(
        id=ep.id,
        project_id=ep.project_id,
        order_index=ep.order_index,
        title=ep.title,
        source_text=ep.source_text,
        char_count=len(ep.source_text or ""),
        summary=ep.summary or "",
        target_shots=ep.target_shots or 6,
        status=ep.status or "pending",
        shot_count=len(ep.shots),
        created_at=ep.created_at,
    )


def _save_split_episodes(
    db: Session,
    proj: Project,
    novel_title: str,
    raw_text: str,
    split_mode: str,
    chars_per_episode: int,
    replace_existing: bool,
) -> list[Episode]:
    chunks = split_novel_into_episodes(raw_text, split_mode=split_mode, chars_per_episode=chars_per_episode)
    if not chunks:
        raise HTTPException(status_code=400, detail="未能从导入内容中解析出有效文本")

    proj.novel_title = novel_title.strip() or proj.name
    if replace_existing:
        for old in list(proj.episodes):
            db.delete(old)
        db.flush()
        start_idx = 0
    else:
        start_idx = db.query(Episode).filter(Episode.project_id == proj.id).count()

    created: list[Episode] = []
    for i, ch in enumerate(chunks):
        # Heuristic default shot count for single-beat AI video pacing (~130 chars/shot, 6 to 30 shots)
        length = len(ch["source_text"])
        auto_shots = max(6, min(30, round(length / 130)))
        ep = Episode(
            project_id=proj.id,
            order_index=start_idx + i,
            title=ch["title"],
            source_text=ch["source_text"],
            target_shots=auto_shots,
            status="pending",
        )
        db.add(ep)
        created.append(ep)

    db.commit()
    for ep in created:
        db.refresh(ep)
    return created


@router.get("/episodes", response_model=list[EpisodeOut])
def list_episodes(project_id: str, db: Session = Depends(get_db)):
    eps = (
        db.query(Episode)
        .filter(Episode.project_id == project_id)
        .order_by(Episode.order_index.asc(), Episode.created_at.asc())
        .all()
    )
    return [serialize_episode(e) for e in eps]


@router.post("/import-text", response_model=list[EpisodeOut])
def import_novel_text(project_id: str, payload: NovelImportTextRequest, db: Session = Depends(get_db)):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    eps = _save_split_episodes(
        db,
        proj,
        payload.novel_title,
        payload.text,
        payload.split_mode,
        payload.chars_per_episode,
        payload.replace_existing,
    )
    return [serialize_episode(e) for e in eps]


@router.post("/import-file", response_model=list[EpisodeOut])
async def import_novel_file(
    project_id: str,
    file: UploadFile = File(...),
    split_mode: str = Form("auto_chapter"),
    chars_per_episode: int = Form(1200),
    replace_existing: bool = Form(True),
    db: Session = Depends(get_db),
):
    """Import a .txt, .md, .docx, or .epub novel file and automatically split it into episodes."""
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    raw = await file.read()
    try:
        text = extract_novel_text_from_file(file.filename or "novel.txt", raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"解析小说文件失败: {exc}")

    title = Path(file.filename or "导入小说").stem
    eps = _save_split_episodes(
        db,
        proj,
        title,
        text,
        split_mode if split_mode in ("auto_chapter", "by_length") else "auto_chapter",
        max(300, min(20000, int(chars_per_episode))),
        replace_existing,
    )
    return [serialize_episode(e) for e in eps]


@router.patch("/episodes/{episode_id}", response_model=EpisodeOut)
def update_episode(project_id: str, episode_id: str, payload: EpisodeUpdate, db: Session = Depends(get_db)):
    ep = db.query(Episode).filter(Episode.id == episode_id, Episode.project_id == project_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="分集不存在")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(ep, k, v)
    db.commit()
    db.refresh(ep)
    return serialize_episode(ep)


@router.delete("/episodes/{episode_id}")
def delete_episode(project_id: str, episode_id: str, db: Session = Depends(get_db)):
    ep = db.query(Episode).filter(Episode.id == episode_id, Episode.project_id == project_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="分集不存在")
    # Also delete shots belonging to this episode to avoid orphaned drafts
    db.query(Shot).filter(Shot.episode_id == episode_id).delete()
    db.delete(ep)
    db.commit()
    return {"ok": True}


@router.post("/extract-bible", response_model=JobTaskOut)
async def run_extract_book_bible(
    project_id: str,
    payload: ExtractBibleRequest,
    db: Session = Depends(get_db),
):
    """Use Gemini long-context to extract global Characters, Scenes, Props, and Episode Summaries."""
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")
    eps = (
        db.query(Episode)
        .filter(Episode.project_id == project_id)
        .order_by(Episode.order_index.asc())
        .limit(payload.max_episodes)
        .all()
    )
    if not eps:
        raise HTTPException(status_code=400, detail="请先导入小说后再提取全书角色与场景设定")

    ep_payload = [{"id": e.id, "order_index": e.order_index, "title": e.title, "source_text": e.source_text} for e in eps]
    novel_title = proj.novel_title or proj.name
    est_cost = 0.02

    job = create_job_record(
        project_id=project_id,
        kind="novel_bible",
        message=f"Gemini 长上下文正在通读《{novel_title}》前 {len(ep_payload)} 集并提炼全书角色/场景库...",
        estimated_cost_usd=est_cost,
    )

    def _worker(progress_cb):
        progress_cb(30, "通读小说文本，提取跨集一致性角色与场景设定...")
        bible, model_used, is_demo = extract_book_bible(novel_title, ep_payload)
        progress_cb(80, "写入项目资产库与分集剧情摘要...")

        session = SessionLocal()
        added_assets = 0
        try:
            p = session.get(Project, project_id)
            if p:
                if bible.get("style_prompt"):
                    p.style_prompt = str(bible["style_prompt"])
                if bible.get("bgm_prompt"):
                    p.bgm_prompt = str(bible["bgm_prompt"])

            existing = {
                a.name: a
                for a in session.query(Asset).filter(Asset.project_id == project_id).all()
            }
            for a_spec in bible.get("assets") or []:
                name = str(a_spec.get("name", "")).strip()
                if not name:
                    continue
                if name in existing:
                    existing[name].description = str(a_spec.get("description") or existing[name].description)
                else:
                    session.add(
                        Asset(
                            project_id=project_id,
                            name=name,
                            kind=str(a_spec.get("kind") or "character"),
                            description=str(a_spec.get("description") or ""),
                        )
                    )
                    added_assets += 1

            summary_map = {
                int(item["order_index"]): str(item.get("summary", ""))
                for item in (bible.get("episode_summaries") or [])
                if "order_index" in item
            }
            for ep_info in ep_payload:
                if ep_info["order_index"] in summary_map:
                    ep_row = session.get(Episode, ep_info["id"])
                    if ep_row:
                        ep_row.summary = summary_map[ep_info["order_index"]]

            session.commit()
        finally:
            session.close()

        record_cost(project_id, job.id, "novel_bible", model_used, est_cost, is_demo, f"全书人设抽取: {novel_title}")
        return {"added_assets": added_assets, "is_demo": is_demo}

    submit_background_job(job.id, _worker)
    return _job_to_out(job)


@router.post("/episodes/{episode_id}/breakdown", response_model=JobTaskOut)
async def run_episode_breakdown(
    project_id: str,
    episode_id: str,
    payload: EpisodeBreakdownRequest,
    db: Session = Depends(get_db),
):
    """Break down a single novel episode into structured storyboard shots linked to global Assets."""
    proj = db.get(Project, project_id)
    ep = db.query(Episode).filter(Episode.id == episode_id, Episode.project_id == project_id).first()
    if not proj or not ep:
        raise HTTPException(status_code=404, detail="项目或分集不存在")

    prev_ep = (
        db.query(Episode)
        .filter(Episode.project_id == project_id, Episode.order_index < ep.order_index)
        .order_by(Episode.order_index.desc())
        .first()
    )
    prev_summary = prev_ep.summary if prev_ep else ""
    assets_list = [
        {"id": a.id, "name": a.name, "kind": a.kind, "description": a.description}
        for a in proj.assets
    ]
    ep_title = ep.title
    ep_text = ep.source_text
    style_prompt = proj.style_prompt
    est_cost = COST_RATES["chat"] * 2

    job = create_job_record(
        project_id=project_id,
        kind="episode_breakdown",
        message=f"正在将「{ep_title}」自动拆解为约 {payload.target_shots} 个影视分镜...",
        estimated_cost_usd=est_cost,
    )

    def _worker(progress_cb):
        progress_cb(30, f"AI 导演正在研读「{ep_title}」原文并设计镜头语言...")
        data, model_used, is_demo = breakdown_episode_to_shots(
            episode_title=ep_title,
            episode_text=ep_text,
            prev_summary=prev_summary,
            project_style=style_prompt,
            assets=assets_list,
            target_shots=payload.target_shots,
        )
        progress_cb(80, "写入结构化分镜并自动绑定全书资产...")

        shots_spec = data.get("shots") or []
        name_to_id = {a["name"]: a["id"] for a in assets_list}

        session = SessionLocal()
        try:
            ep_row = session.get(Episode, episode_id)
            if payload.replace_existing:
                session.query(Shot).filter(Shot.project_id == project_id, Shot.episode_id == episode_id).delete()
                session.flush()
                start_order = 0
            else:
                start_order = (
                    session.query(Shot)
                    .filter(Shot.project_id == project_id, Shot.episode_id == episode_id)
                    .count()
                )

            for offset, s_spec in enumerate(shots_spec):
                matched_ids = [name_to_id[n] for n in (s_spec.get("asset_names") or []) if n in name_to_id]
                raw_dialogue = str(s_spec.get("dialogue") or "")
                raw_mode = str(s_spec.get("dialogue_mode") or "").strip().lower()
                if raw_mode not in ("spoken", "narration", "none"):
                    raw_mode = "spoken" if raw_dialogue.strip() else "none"
                session.add(
                    Shot(
                        project_id=project_id,
                        episode_id=episode_id,
                        order_index=start_order + offset,
                        title=str(s_spec.get("title") or f"{ep_title} · 镜{start_order + offset + 1}"),
                        shot_type=str(s_spec.get("shot_type") or "中景"),
                        camera_movement=str(s_spec.get("camera_movement") or "缓慢推进"),
                        visual_prompt_zh=str(s_spec.get("visual_prompt_zh") or ""),
                        video_prompt_en=str(s_spec.get("video_prompt_en") or ""),
                        dialogue=raw_dialogue,
                        dialogue_mode=raw_mode,
                        sfx_prompt=str(s_spec.get("sfx_prompt") or ""),
                        duration_sec=int(s_spec.get("duration_sec") or 5),
                        asset_ids_json=json.dumps(matched_ids),
                    )
                )

            if ep_row:
                ep_row.target_shots = payload.target_shots
                ep_row.status = "parsed"
                if data.get("summary"):
                    ep_row.summary = str(data["summary"])
            session.commit()
        finally:
            session.close()

        record_cost(project_id, job.id, "episode_breakdown", model_used, est_cost, is_demo, f"小说拆镜: {ep_title}")
        return {"episode_id": episode_id, "created_shots": len(shots_spec), "is_demo": is_demo}

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
