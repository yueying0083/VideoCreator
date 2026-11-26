from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import COST_RATES
from app.database import Asset, ChatMessage, Project, Shot, get_db
from app.schemas import ChatMessageOut, ChatSendRequest
from app.services.director_agent import run_director_turn
from app.services.task_runner import record_cost

router = APIRouter(prefix="/api/projects/{project_id}/chat", tags=["chat"])


def serialize_message(m: ChatMessage) -> ChatMessageOut:
    proposal = None
    if m.proposal_json:
        try:
            proposal = json.loads(m.proposal_json)
        except Exception:
            proposal = None
    return ChatMessageOut(
        id=m.id,
        project_id=m.project_id,
        role=m.role,
        content=m.content,
        proposal=proposal,
        proposal_applied=m.proposal_applied,
        created_at=m.created_at,
    )


@router.get("", response_model=list[ChatMessageOut])
def list_messages(project_id: str, db: Session = Depends(get_db)):
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.project_id == project_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    return [serialize_message(m) for m in msgs]


@router.post("", response_model=ChatMessageOut)
def send_director_message(project_id: str, payload: ChatSendRequest, db: Session = Depends(get_db)):
    proj = db.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="项目不存在")

    user_msg = ChatMessage(project_id=project_id, role="user", content=payload.content.strip())
    db.add(user_msg)
    db.commit()

    history_rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.project_id == project_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    history = [{"role": r.role, "content": r.content} for r in history_rows[:-1]]

    project_context = {
        "name": proj.name,
        "description": proj.description,
        "aspect_ratio": proj.aspect_ratio,
        "style_prompt": proj.style_prompt,
        "assets": [
            {
                "id": a.id,
                "name": a.name,
                "kind": a.kind,
                "description": a.description,
                "file_path": a.file_path,
            }
            for a in proj.assets
        ],
        "shots": [
            {
                "order": s.order_index + 1,
                "title": s.title,
                "shot_type": s.shot_type,
                "camera_movement": s.camera_movement,
                "visual_prompt_zh": s.visual_prompt_zh,
                "duration_sec": s.duration_sec,
            }
            for s in proj.shots
        ],
    }

    try:
        result, model_used, is_demo = run_director_turn(project_context, history, payload.content.strip())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"导演 Agent 调用失败: {exc}")

    reply_text = str(result.get("reply") or "已收到你的指令。")
    proposal = result.get("proposal")

    ai_msg = ChatMessage(
        project_id=project_id,
        role="assistant",
        content=reply_text,
        proposal_json=json.dumps(proposal, ensure_ascii=False) if proposal else None,
    )
    db.add(ai_msg)
    db.commit()
    db.refresh(ai_msg)

    record_cost(project_id, None, "chat", model_used, COST_RATES["chat"], is_demo, "导演对话规划")
    return serialize_message(ai_msg)


@router.post("/{message_id}/apply")
def apply_director_proposal(project_id: str, message_id: str, db: Session = Depends(get_db)):
    """Human-in-the-loop gate: apply an AI Director's storyboard & asset proposal to the project."""
    proj = db.get(Project, project_id)
    msg = db.query(ChatMessage).filter(ChatMessage.id == message_id, ChatMessage.project_id == project_id).first()
    if not proj or not msg or not msg.proposal_json:
        raise HTTPException(status_code=404, detail="未找到可应用的导演提案")

    proposal = json.loads(msg.proposal_json)

    if proposal.get("style_prompt"):
        proj.style_prompt = str(proposal["style_prompt"])
    if proposal.get("bgm_prompt"):
        proj.bgm_prompt = str(proposal["bgm_prompt"])

    # Upsert assets by name
    existing_assets = {a.name: a for a in proj.assets}
    for a_spec in proposal.get("assets") or []:
        name = str(a_spec.get("name", "")).strip()
        if not name:
            continue
        if name in existing_assets:
            existing_assets[name].description = str(a_spec.get("description") or existing_assets[name].description)
        else:
            new_a = Asset(
                project_id=project_id,
                name=name,
                kind=str(a_spec.get("kind") or "character"),
                description=str(a_spec.get("description") or ""),
            )
            db.add(new_a)
            db.flush()
            existing_assets[name] = new_a

    # Apply shots (replace or append)
    shots_spec = proposal.get("shots") or []
    if shots_spec:
        mode = proposal.get("mode", "replace_shots")
        if mode == "replace_shots":
            for old_s in list(proj.shots):
                db.delete(old_s)
            db.flush()
            start_idx = 0
        else:
            start_idx = db.query(Shot).filter(Shot.project_id == project_id).count()

        for offset, s_spec in enumerate(shots_spec):
            asset_names = s_spec.get("asset_names") or []
            matched_ids = [existing_assets[n].id for n in asset_names if n in existing_assets]
            raw_dialogue = str(s_spec.get("dialogue") or "")
            raw_mode = str(s_spec.get("dialogue_mode") or "").strip().lower()
            if raw_mode not in ("spoken", "narration", "none"):
                raw_mode = "spoken" if raw_dialogue.strip() else "none"
            shot = Shot(
                project_id=project_id,
                order_index=start_idx + offset,
                title=str(s_spec.get("title") or f"镜头 {start_idx + offset + 1}"),
                shot_type=str(s_spec.get("shot_type") or "中景"),
                camera_movement=str(s_spec.get("camera_movement") or "缓慢推进"),
                visual_prompt_zh=str(s_spec.get("visual_prompt_zh") or ""),
                video_prompt_en=str(s_spec.get("video_prompt_en") or ""),
                dialogue=raw_dialogue,
                dialogue_mode=raw_mode,
                sfx_prompt=str(s_spec.get("sfx_prompt") or ""),
                duration_sec=int(s_spec.get("duration_sec") or 6),
                asset_ids_json=json.dumps(matched_ids),
            )
            db.add(shot)

    msg.proposal_applied = True
    db.commit()
    return {"ok": True, "applied_shots": len(shots_spec), "applied_assets": len(proposal.get("assets") or [])}
