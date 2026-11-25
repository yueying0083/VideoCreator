from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import RuntimeSettings, load_settings
from app.services.genai_utils import create_genai_client, detect_mime
from app.services.storage import resolve_abs_path


class ProposalAssetItem(BaseModel):
    name: str
    kind: Literal["character", "scene", "prop"] = "character"
    description: str


class ProposalShotItem(BaseModel):
    title: str
    shot_type: str = "中景"
    camera_movement: str = "缓慢推进"
    visual_prompt_zh: str
    video_prompt_en: str
    dialogue: str = ""
    sfx_prompt: str = ""
    duration_sec: int = Field(default=6, ge=3, le=15)
    asset_names: list[str] = Field(default_factory=list)


class DirectorProposalSchema(BaseModel):
    title: str
    mode: Literal["replace_shots", "append_shots", "update_style"] = "replace_shots"
    style_prompt: str = ""
    bgm_prompt: str = ""
    assets: list[ProposalAssetItem] = Field(default_factory=list)
    shots: list[ProposalShotItem] = Field(default_factory=list)


class DirectorTurnOutput(BaseModel):
    reply: str = Field(description="Professional Chinese director reply to the creator.")
    proposal: DirectorProposalSchema | None = Field(
        default=None,
        description="Structured storyboard & asset proposal when the user asks to plan/modify shots, else null.",
    )


DIRECTOR_SYSTEM_PROMPT = """你是一位顶级商业影视与 AI 短片总导演（对标 MiniMax Design 导演 Agent），正在与用户合作制作一条多镜头 AI 短片。
你的职责：
1. 理解用户的创意、剧本、修改意见，并结合当前已挂载的资产定妆图（如有），维护角色、场景、光影风格的跨镜头一致性。
2. 当用户提出创作新故事、拆解分镜、增加/修改镜头或设计角色场景时，输出结构化的 `proposal`（提案），让用户确认后再落盘执行（人机确认，避免盲烧算力）。
3. 每个镜头必须同时给出中文视觉描述（visual_prompt_zh）和电影级英文视频提示词（video_prompt_en）：
   - 适用于 Nano Banana 2.1、Veo 3.1、Gemini Omni 1.2 Flash 与 Google Flow；
   - 遵循 Omni 1.2 Flash 最佳实践：默认明确单镜连续不切镜（如 "Continuous, unbroken single shot, no scene cuts"）、包含景别/运镜/光影/同期声描述，严禁使用 `<FIRST_FRAME>`、`<IMAGE_REF_1>` 等已废弃 XML 标签，需引用参考图时用自然语言表述。
4. 若需要配乐，在 `bgm_prompt` 给出适配 Lyria 3.5 的英文音乐提示词。"""


def _build_demo_director_response(user_message: str, project_name: str, existing_shots_count: int) -> dict[str, Any]:
    topic = user_message.strip()[:48]
    mode = "append_shots" if existing_shots_count > 0 and ("加" in user_message or "续" in user_message) else "replace_shots"
    return {
        "reply": (
            f"【Demo 导演模式】已收到你的创意「{topic}」！我为你拆解了一套包含角色/场景定妆资产与 3 个连贯镜头的分镜提案。"
            "你可以先审阅下方分镜卡片，确认无误后点击「应用到分镜板」，再按「生成首帧 → Veo / Omni / Flow」推进。"
        ),
        "proposal": {
            "title": f"{project_name} · 导演分镜提案（3 镜头）",
            "mode": mode,
            "style_prompt": "电影级青橙色调，35mm 胶片质感，细腻体积光与自然物理光影，高一致性角色表现",
            "bgm_prompt": "Atmospheric cinematic synthwave and soft piano underscore, slowly building emotional tension, 96 BPM, 48kHz stereo",
            "assets": [
                {
                    "name": "主角·林澈",
                    "kind": "character",
                    "description": "26岁东亚青年，利落黑短发，身穿做旧深灰机能风外套与银色耳机，眼神沉静专注，写实电影光影风格",
                },
                {
                    "name": "霓虹雨夜长街",
                    "kind": "scene",
                    "description": "雨后的未来都市老街，湿润沥青路面反射蓝紫与琥珀色霓虹招牌，薄雾弥漫，电影级景深",
                },
            ],
            "shots": [
                {
                    "title": "镜头 1 · 雨夜入场",
                    "shot_type": "远景",
                    "camera_movement": "缓慢推进",
                    "visual_prompt_zh": f"围绕「{topic}」开场：霓虹雨夜长街，主角林澈撑着透明雨伞从街角缓步走入镜头，地面水洼倒映霓虹光斑",
                    "video_prompt_en": "Continuous, unbroken single shot, wide cinematic establishing shot, slow dolly forward along a rain-slicked neon alley at night, a 26-year-old East Asian man in a dark grey technical jacket holding a clear umbrella walks calmly into frame, glowing reflections on wet asphalt, gentle rain and distant city hum audio, 35mm anamorphic film look",
                    "dialogue": "这座城市从不真正入睡。",
                    "sfx_prompt": "细雨滴落伞面声、远处低沉都市车流声",
                    "duration_sec": 6,
                    "asset_names": ["主角·林澈", "霓虹雨夜长街"],
                },
                {
                    "title": "镜头 2 · 驻足凝视",
                    "shot_type": "中近景",
                    "camera_movement": "侧面跟拍",
                    "visual_prompt_zh": "镜头切至林澈侧面中近景，他微微抬头看向高处闪烁的全息灯牌，雨水沿着伞骨滑落，侧逆光勾勒面部轮廓",
                    "video_prompt_en": "Continuous, unbroken single shot, medium close-up side tracking shot of the 26-year-old East Asian man in a dark grey jacket stopping to look up at a glowing holographic sign, warm rim light on his face, raindrops dripping off the umbrella edge, subtle breath and muffled neon buzz sound, shallow depth of field",
                    "dialogue": "而我们的故事，才刚刚开始。",
                    "sfx_prompt": "霓虹电流嗡鸣声、轻缓脚步停顿声",
                    "duration_sec": 6,
                    "asset_names": ["主角·林澈", "霓虹雨夜长街"],
                },
                {
                    "title": "镜头 3 · 光影收束",
                    "shot_type": "特写",
                    "camera_movement": "缓慢拉远",
                    "visual_prompt_zh": "特写聚焦在林澈收起雨伞后亮起的掌心投影微光，镜头缓缓拉远，人物融入璀璨夜景中形成视觉高潮",
                    "video_prompt_en": "Continuous, unbroken single shot, close-up transitioning into a slow pull-back shot, the man lowers his umbrella revealing a soft glowing light in his palm, cinematic volumetric mist and glowing bokeh lights behind him, swelling atmospheric soundtrack and crisp rain ambience",
                    "dialogue": "",
                    "sfx_prompt": "清脆微光启动音效、雨声渐弱融入配乐",
                    "duration_sec": 6,
                    "asset_names": ["主角·林澈", "霓虹雨夜长街"],
                },
            ],
        },
    }


def run_director_turn(
    project_context: dict[str, Any],
    history: list[dict[str, str]],
    user_message: str,
    settings: RuntimeSettings | None = None,
) -> tuple[dict[str, Any], str, bool]:
    cfg = settings or load_settings()
    if cfg.effective_mode == "demo":
        resp = _build_demo_director_response(
            user_message,
            project_context.get("name", "未命名项目"),
            len(project_context.get("shots", [])),
        )
        return resp, "demo-director", True

    client = create_genai_client(cfg, timeout_seconds=120)

    input_parts: list[dict[str, Any]] = []
    attached_names: list[str] = []

    # Attach up to 6 existing asset reference images inline so Gemini 4 sees actual characters/scenes
    for asset_item in project_context.get("assets", [])[:6]:
        rel_path = asset_item.get("file_path")
        if not rel_path:
            continue
        try:
            abs_p = resolve_abs_path(rel_path)
        except ValueError:
            continue
        if abs_p and abs_p.exists() and abs_p.stat().st_size <= 8 * 1024 * 1024:
            mime = detect_mime(abs_p, "image/png")
            if mime.startswith("image/"):
                b64 = base64.b64encode(abs_p.read_bytes()).decode("ascii")
                input_parts.append({"type": "image", "data": b64, "mime_type": mime})
                attached_names.append(f"{asset_item.get('name')} ({asset_item.get('kind')})")

    # Strip internal file_path from JSON context
    clean_ctx = dict(project_context)
    clean_ctx["assets"] = [
        {k: v for k, v in a.items() if k != "file_path"} for a in project_context.get("assets", [])
    ]
    context_blob = json.dumps(clean_ctx, ensure_ascii=False, indent=2)

    convo_lines = []
    for msg in history[-10:]:
        role_label = "创作者" if msg["role"] == "user" else "导演Agent"
        convo_lines.append(f"{role_label}: {msg['content']}")
    convo_text = "\n".join(convo_lines)

    visual_ref_note = (
        f"\n已附带 {len(attached_names)} 张项目现有资产参考图（顺序对应：{', '.join(attached_names)}）。"
        if attached_names
        else ""
    )

    full_prompt = (
        f"当前项目上下文（JSON）：\n{context_blob}{visual_ref_note}\n\n"
        f"最近对话记录：\n{convo_text}\n\n"
        f"创作者最新指令：\n{user_message}\n\n"
        "请严格按照 JSON Schema 输出回复与可选提案。"
    )
    input_parts.append({"type": "text", "text": full_prompt})

    interaction = client.interactions.create(
        model=cfg.text_model,
        system_instruction=DIRECTOR_SYSTEM_PROMPT,
        input=input_parts,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": DirectorTurnOutput.model_json_schema(),
        },
        store=False,
    )
    raw = (interaction.output_text or "{}").strip()
    try:
        parsed = DirectorTurnOutput.model_validate_json(raw).model_dump()
    except Exception:
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                parsed = {"reply": raw, "proposal": None}
            parsed.setdefault("reply", "已生成导演建议。")
            parsed.setdefault("proposal", None)
        except json.JSONDecodeError:
            parsed = {"reply": raw, "proposal": None}

    return parsed, cfg.text_model, False
