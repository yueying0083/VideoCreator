from __future__ import annotations

import base64
import hashlib
import json
import textwrap
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from app.config import RuntimeSettings, load_settings
from app.services.genai_utils import (
    create_genai_client,
    create_vertex_client,
    detect_mime,
    extract_interaction_media,
    upload_file_to_gemini,
)
from app.services.media_renderer import aspect_to_dimensions, generate_demo_music, generate_demo_video


class VideoQaOutput(BaseModel):
    score: int = Field(ge=1, le=10, description="Overall quality score from 1 to 10.")
    summary: str = Field(description="Concise Chinese summary within 80 characters.")
    issues: list[str] = Field(default_factory=list, description="List of detected visual/continuity issues.")
    improved_prompt_en: str = Field(description="Refined English prompt for regenerating this shot.")


def _load_pil_font(size: int):
    candidates = [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for fp in candidates:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def render_demo_image(
    output_path: Path,
    title: str,
    subtitle: str,
    aspect_ratio: str = "16:9",
    badge: str = "DEMO KEYFRAME",
) -> Path:
    """Generate a sleek cinema-styled placeholder PNG for Demo Mode."""
    w, h = aspect_to_dimensions(aspect_ratio, "720p")
    digest = hashlib.md5((title + subtitle).encode("utf-8")).digest()
    c1 = (24 + digest[0] % 48, 28 + digest[1] % 50, 56 + digest[2] % 80)
    c2 = (12 + digest[3] % 24, 15 + digest[4] % 30, 26 + digest[5] % 40)

    img = Image.new("RGB", (w, h), c2)
    draw = ImageDraw.Draw(img)

    for y in range(h):
        t = y / max(1, h - 1)
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    guide_color = (255, 255, 255)
    for frac in (1 / 3, 2 / 3):
        gx = int(w * frac)
        gy = int(h * frac)
        draw.line([(gx, 40), (gx, h - 40)], fill=(95, 110, 145), width=1)
        draw.line([(40, gy), (w - 40, gy)], fill=(95, 110, 145), width=1)

    margin = 36
    draw.rectangle([margin, margin, w - margin, h - margin], outline=(140, 155, 210), width=2)

    font_badge = _load_pil_font(22)
    font_title = _load_pil_font(42)
    font_sub = _load_pil_font(24)

    draw.rounded_rectangle([margin + 20, margin + 20, margin + 320, margin + 62], radius=8, fill=(99, 102, 241))
    draw.text((margin + 36, margin + 29), badge, fill=guide_color, font=font_badge)

    center_y = int(h * 0.36)
    wrapped_title = textwrap.wrap(title.strip() or "Studio Frame", width=22)[:2]
    for i, line in enumerate(wrapped_title):
        draw.text((margin + 28, center_y + i * 54), line, fill=(245, 248, 255), font=font_title)

    wrapped_sub = textwrap.wrap(subtitle.strip(), width=42)[:5]
    sub_y = center_y + len(wrapped_title) * 54 + 22
    for i, line in enumerate(wrapped_sub):
        draw.text((margin + 28, sub_y + i * 34), line, fill=(203, 213, 225), font=font_sub)

    draw.text(
        (margin + 28, h - margin - 40),
        f"Aspect {aspect_ratio}  |  Local Demo Renderer (配置 GEMINI_API_KEY 后将使用 Nano Banana 2.1 真实渲染)",
        fill=(148, 163, 184),
        font=_load_pil_font(18),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="PNG")
    return output_path


def generate_image(
    prompt: str,
    output_path: Path,
    aspect_ratio: str = "16:9",
    reference_image_paths: list[Path] | None = None,
    badge_title: str = "Keyframe",
    settings: RuntimeSettings | None = None,
) -> tuple[Path, str, bool]:
    """
    Generate an image with Nano Banana 2.1 (gemini-nano-banana-2.1 via Interactions API) or Demo Renderer.
    Supports up to 14 reference images for character/style fusion.
    Returns (output_path, model_used, is_demo).
    """
    cfg = settings or load_settings()
    if cfg.effective_mode == "demo":
        render_demo_image(output_path, badge_title, prompt, aspect_ratio=aspect_ratio, badge="DEMO · NANO BANANA")
        return output_path, "demo-image", True

    client = create_genai_client(cfg, timeout_seconds=120)
    ref_paths = [p for p in (reference_image_paths or []) if p and p.exists()][:14]

    input_parts: list[dict[str, Any]] = []
    for ref_p in ref_paths:
        if ref_p.stat().st_size <= 8 * 1024 * 1024:
            b64 = base64.b64encode(ref_p.read_bytes()).decode("ascii")
            input_parts.append({"type": "image", "data": b64, "mime_type": detect_mime(ref_p, "image/png")})
    input_parts.append({"type": "text", "text": prompt})

    img_bytes: bytes | None = None
    try:
        interaction = client.interactions.create(
            model=cfg.image_model,
            input=input_parts if len(input_parts) > 1 else prompt,
            response_format={
                "type": "image",
                "aspect_ratio": aspect_ratio,
                "image_size": "2K",
            },
            store=False,
        )
        img_bytes = extract_interaction_media(client, interaction, "image")
    except Exception:
        # Fallback for user-configured legacy image models if Interactions API rejects them
        from google.genai import types  # type: ignore

        contents: list[Any] = [Image.open(p) for p in ref_paths[:6]] + [prompt]
        response = client.models.generate_content(
            model=cfg.image_model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            ),
        )
        for candidate in getattr(response, "candidates", []) or []:
            parts = getattr(getattr(candidate, "content", None), "parts", []) or []
            for part in parts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    img_bytes = bytes(inline.data)
                    break
            if img_bytes:
                break

    if not img_bytes:
        raise RuntimeError(f"模型 {cfg.image_model} 未返回图像数据，请检查提示词是否触发内容安全限制。")

    img = Image.open(BytesIO(img_bytes))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="PNG")
    return output_path, cfg.image_model, False


def generate_video(
    engine: str,
    prompt_en: str,
    output_path: Path,
    duration_sec: int = 6,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    mode: str = "generate",
    start_frame_path: Path | None = None,
    end_frame_path: Path | None = None,
    source_video_path: Path | None = None,
    reference_image_paths: list[Path] | None = None,
    reference_video_paths: list[Path] | None = None,
    first_frame_asset_id: str | None = None,
    last_frame_asset_id: str | None = None,
    source_video_asset_id: str | None = None,
    ref_image_asset_ids: list[str | None] | None = None,
    ref_video_asset_ids: list[str | None] | None = None,
    with_audio: bool = True,
    strip_audio: bool = False,
    previous_interaction_id: str | None = None,
    task_override: str | None = None,
    badge_title: str = "Shot",
    on_progress: Callable[[int, str], None] | None = None,
    settings: RuntimeSettings | None = None,
) -> tuple[Path, str, bool, str | None]:
    """
    Generate video via Gemini Omni 1.2 Flash, Vertex AI Veo 3.1, or Demo FFmpeg renderer.
    Returns (output_path, model_used, is_demo, interaction_id).
    """
    cfg = settings or load_settings()

    # ---- Engine B: Gemini Omni 1.2 Flash (handles both Live & Demo consistently) ----
    if engine == "omni_flash":
        from app.services.omni_engine import generate_omni_video

        def _on_status(_status: str, pct: int, msg: str) -> None:
            if on_progress:
                on_progress(pct, msg)

        return generate_omni_video(
            prompt_en=prompt_en,
            output_path=output_path,
            mode=mode,
            duration_sec=duration_sec,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            start_frame_path=start_frame_path,
            end_frame_path=end_frame_path,
            source_video_path=source_video_path,
            ref_image_paths=reference_image_paths,
            ref_video_paths=reference_video_paths,
            first_frame_asset_id=first_frame_asset_id,
            last_frame_asset_id=last_frame_asset_id,
            source_video_asset_id=source_video_asset_id,
            ref_image_asset_ids=ref_image_asset_ids,
            ref_video_asset_ids=ref_video_asset_ids,
            strip_audio=strip_audio or (not with_audio),
            previous_interaction_id=previous_interaction_id,
            task_override=task_override,
            badge_title=badge_title,
            on_status=_on_status,
            settings=cfg,
        )

    if cfg.effective_mode == "demo":
        if on_progress:
            on_progress(25, "Demo 模式：准备关键帧...")
        src_img = start_frame_path
        if not src_img or not src_img.exists():
            tmp_img = output_path.with_suffix(".tmp.png")
            render_demo_image(tmp_img, badge_title, prompt_en, aspect_ratio=aspect_ratio, badge=f"DEMO · {engine.upper()}")
            src_img = tmp_img
        if on_progress:
            on_progress(60, "Demo 模式：本地 FFmpeg 合成动态演示片段...")
        generate_demo_video(output_path, src_img, duration_sec=duration_sec, aspect_ratio=aspect_ratio, with_audio=with_audio)
        if src_img != start_frame_path and src_img.exists():
            src_img.unlink(missing_ok=True)
        return output_path, f"demo-{engine}", True, None

    # ---- Engine A: Vertex AI Veo 3.1 (Lite / Fast / Standard) ----
    from google.genai import types  # type: ignore

    model_map = {
        "veo_lite": cfg.veo_lite_model,
        "veo_fast": cfg.veo_fast_model,
        "veo_standard": cfg.veo_standard_model,
    }
    model_id = model_map.get(engine, cfg.veo_lite_model)
    client = create_vertex_client(cfg)

    if on_progress:
        on_progress(15, f"向 Vertex AI 提交 {model_id} 异步任务...")

    config_kwargs: dict[str, Any] = {
        "aspect_ratio": aspect_ratio,
        "duration_seconds": duration_sec,
        "generate_audio": with_audio,
    }

    if end_frame_path and end_frame_path.exists():
        config_kwargs["last_frame"] = types.Image.from_file(location=str(end_frame_path))

    refs = []
    for rp in (reference_image_paths or [])[:3]:
        if rp and rp.exists():
            refs.append(
                types.VideoGenerationReferenceImage(
                    image=types.Image.from_file(location=str(rp)),
                    reference_type="asset",
                )
            )
    if refs and not start_frame_path:
        config_kwargs["reference_images"] = refs

    call_kwargs: dict[str, Any] = {
        "model": model_id,
        "prompt": prompt_en,
        "config": types.GenerateVideosConfig(**config_kwargs),
    }
    if start_frame_path and start_frame_path.exists():
        call_kwargs["image"] = types.Image.from_file(location=str(start_frame_path))

    operation = client.models.generate_videos(**call_kwargs)
    poll_count = 0
    while not operation.done:
        poll_count += 1
        pct = min(88, 20 + poll_count * 6)
        if on_progress:
            on_progress(pct, f"Vertex AI {model_id} 渲染中（第 {poll_count} 次轮询）...")
        time.sleep(10)
        operation = client.operations.get(operation)

    if getattr(operation, "error", None):
        raise RuntimeError(f"Veo 生成失败: {operation.error}")

    generated_videos = getattr(getattr(operation, "response", None), "generated_videos", None) or []
    if not generated_videos:
        raise RuntimeError("Veo 任务完成但未返回视频文件（可能触发了安全过滤）。")

    vid_obj = generated_videos[0].video
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if getattr(vid_obj, "video_bytes", None):
        output_path.write_bytes(vid_obj.video_bytes)
    else:
        downloaded = client.files.download(file=vid_obj)
        output_path.write_bytes(downloaded)

    return output_path, model_id, False, None


def generate_music(
    prompt: str,
    output_path: Path,
    mode: str = "clip",
    settings: RuntimeSettings | None = None,
) -> tuple[Path, str, bool]:
    cfg = settings or load_settings()
    if cfg.effective_mode == "demo":
        generate_demo_music(output_path, duration_sec=18)
        return output_path, "demo-lyria", True

    client = create_genai_client(cfg, timeout_seconds=180)
    if mode == "pro" and "lyria-3-" in cfg.music_model:
        model_id = "lyria-3-pro-preview"
    else:
        model_id = cfg.music_model

    interaction = client.interactions.create(model=model_id, input=prompt)
    audio_bytes = extract_interaction_media(client, interaction, "audio")
    if not audio_bytes:
        raise RuntimeError(f"{model_id} 未返回音频数据，请检查模型权限或稍后重试。")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)
    return output_path, model_id, False


def review_video_qa(
    video_path: Path,
    shot_title: str,
    visual_prompt_zh: str,
    video_prompt_en: str,
    settings: RuntimeSettings | None = None,
) -> tuple[dict[str, Any], str, bool]:
    """Use Gemini 4 multimodal video understanding via Interactions API to critique a take."""
    cfg = settings or load_settings()
    if cfg.effective_mode == "demo":
        return (
            {
                "score": 8,
                "summary": f"【Demo 审片】镜头「{shot_title}」画面构图稳定、节奏自然，与分镜描述吻合度较高。",
                "issues": ["Demo 模式下为模拟审片结果；填入 GEMINI_API_KEY 后将由 Gemini 4 真实逐帧看片质检"],
                "improved_prompt_en": f"{video_prompt_en}, cinematic 35mm lens, natural volumetric lighting, smooth motion continuity",
            },
            "demo-qa",
            True,
        )

    client = create_genai_client(cfg, timeout_seconds=180)
    vid_uri, vid_mime, _ = upload_file_to_gemini(
        client,
        video_path,
        display_name=f"qa_{video_path.name}",
        mime_type="video/mp4",
    )
    prompt = (
        "你是专业影视后期与 AI 视频审片质检导演。请仔细观看这段视频，结合原分镜需求给出严格客观的评估。\n"
        f"- 镜头标题: {shot_title}\n"
        f"- 中文画面需求: {visual_prompt_zh}\n"
        f"- 英文生成提示词: {video_prompt_en}\n\n"
        "请严格按照 JSON Schema 输出评分、简明中文评价、发现的问题点列表，以及优化后的完整英文重拍提示词。"
    )
    interaction = client.interactions.create(
        model=cfg.text_model,
        input=[
            {"type": "video", "uri": vid_uri, "mime_type": vid_mime},
            {"type": "text", "text": prompt},
        ],
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": VideoQaOutput.model_json_schema(),
        },
        store=False,
    )
    raw = (interaction.output_text or "{}").strip()
    try:
        parsed = VideoQaOutput.model_validate_json(raw).model_dump()
    except Exception:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"score": 7, "summary": raw[:120], "issues": [], "improved_prompt_en": video_prompt_en}
    return parsed, cfg.text_model, False
