from __future__ import annotations

import json
from typing import Any

from app.config import RuntimeSettings, load_settings
from app.services.google_ai import _get_gemini_client


DIRECTOR_SYSTEM_PROMPT = """你是一位顶级商业影视与 AI 短片总导演（对标 MiniMax Design 导演 Agent），正在与用户合作制作一条多镜头 AI 短片。
你的职责：
1. 理解用户的创意、剧本、修改意见，并维护角色、场景、光影风格的跨镜头一致性。
2. 当用户提出创作新故事、拆解分镜、增加/修改镜头或设计角色场景时，输出结构化的 `proposal`（提案），让用户确认后再落盘执行（人机确认，避免盲烧算力）。
3. 每个镜头必须同时给出中文视觉描述（visual_prompt_zh）和电影级英文视频提示词（video_prompt_en，包含景别、运镜、主体细节、光影、氛围与同期声描述），以便直接送入 Nano Banana 2 与 Veo 3.1 / Google Flow。

请始终严格返回如下 JSON 格式（不要输出 Markdown 代码块包裹之外的文字）：
{
  "reply": "你对用户的专业导演回复（简洁清晰，中文）",
  "proposal": null 或 {
    "title": "本次提案标题，例如：赛博雨夜追逐 · 4镜头分镜提案",
    "mode": "replace_shots" 或 "append_shots" 或 "update_style",
    "style_prompt": "可选，整体视觉风格建议",
    "bgm_prompt": "可选，给 Lyria 3 的英文配乐提示词",
    "assets": [
      {"name": "角色或场景名", "kind": "character|scene|prop", "description": "详细视觉特征档案(Character Bible)，便于跨镜头保持一致"}
    ],
    "shots": [
      {
        "title": "镜头标题",
        "shot_type": "远景|全景|中景|近景|特写",
        "camera_movement": "缓慢推进|横摇|跟拍|俯拍|拉远|固定机位",
        "visual_prompt_zh": "中文详细画面描述",
        "video_prompt_en": "Detailed cinematic English prompt for Veo 3.1 including lighting, motion, and synchronized ambient sound/dialogue",
        "dialogue": "可选对白或旁白",
        "sfx_prompt": "环境音/音效提示",
        "duration_sec": 6,
        "asset_names": ["本镜头出现的资产名称"]
      }
    ]
  }
}
"""


def _build_demo_director_response(user_message: str, project_name: str, existing_shots_count: int) -> dict[str, Any]:
    topic = user_message.strip()[:48]
    mode = "append_shots" if existing_shots_count > 0 and ("加" in user_message or "续" in user_message) else "replace_shots"
    return {
        "reply": (
            f"【Demo 导演模式】已收到你的创意「{topic}」！我为你拆解了一套包含角色/场景定妆资产与 3 个连贯镜头的分镜提案。"
            "你可以先审阅下方分镜卡片，确认无误后点击「应用到分镜板」，再按「生成首帧 → Veo Lite 打样 / Flow 精渲」推进。"
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
                    "video_prompt_en": "Wide cinematic establishing shot, slow dolly forward along a rain-slicked neon alley at night, a 26-year-old East Asian man in a dark grey technical jacket holding a clear umbrella walks calmly into frame, glowing reflections on wet asphalt, gentle rain and distant city hum audio, 35mm anamorphic film look",
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
                    "video_prompt_en": "Medium close-up side tracking shot of the 26-year-old East Asian man in a dark grey jacket stopping to look up at a glowing holographic sign, warm rim light on his face, raindrops dripping off the umbrella edge, subtle breath and muffled neon buzz sound, shallow depth of field",
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
                    "video_prompt_en": "Close-up transitioning into a slow pull-back shot, the man lowers his umbrella revealing a soft glowing light in his palm, cinematic volumetric mist and glowing bokeh lights behind him, swelling atmospheric soundtrack and crisp rain ambience",
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

    from google.genai import types  # type: ignore

    client = _get_gemini_client(cfg)

    context_blob = json.dumps(project_context, ensure_ascii=False, indent=2)
    convo_lines = []
    for msg in history[-10:]:
        role_label = "创作者" if msg["role"] == "user" else "导演Agent"
        convo_lines.append(f"{role_label}: {msg['content']}")
    convo_text = "\n".join(convo_lines)

    full_prompt = (
        f"当前项目上下文（JSON）：\n{context_blob}\n\n"
        f"最近对话记录：\n{convo_text}\n\n"
        f"创作者最新指令：\n{user_message}\n\n"
        "请按照系统要求返回严格 JSON。"
    )

    response = client.models.generate_content(
        model=cfg.text_model,
        contents=full_prompt,
        config=types.GenerateContentConfig(
            system_instruction=DIRECTOR_SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.7,
        ),
    )
    raw = (response.text or "{}").strip()
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            parsed = {"reply": raw, "proposal": None}
        parsed.setdefault("reply", "已生成导演建议。")
        parsed.setdefault("proposal", None)
    except json.JSONDecodeError:
        parsed = {"reply": raw, "proposal": None}

    return parsed, cfg.text_model, False
