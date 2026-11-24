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

from app.config import RuntimeSettings, load_settings
from app.services.media_renderer import aspect_to_dimensions, generate_demo_music, generate_demo_video


def _get_gemini_client(settings: RuntimeSettings):
    from google import genai  # type: ignore

    if not settings.gemini_api_key:
        raise RuntimeError("未配置 GEMINI_API_KEY。请在根目录 .env 或网页右上角「设置」中填入 Google AI Studio API Key。")
    return genai.Client(api_key=settings.gemini_api_key)


def _get_vertex_client(settings: RuntimeSettings):
    from google import genai  # type: ignore

    if not settings.vertex_project_id:
        raise RuntimeError(
            "调用 Veo 3.1 正式版需要配置 Vertex AI（VERTEX_PROJECT_ID）。"
            "请在 .env 中配置 GCP 项目，或将视频引擎切换为 Gemini Omni 1.2 Flash（仅需 GEMINI_API_KEY），"
            "或点击「复制 Flow 创作包」使用 Google Flow 网页端 25,000 Ultra 积分生成。"
        )
    return genai.Client(
        vertexai=True,
        project=settings.vertex_project_id,
        location=settings.vertex_location or "us-central1",
    )


def _load_pil_font(size: int):
    candidates = [
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

    # Smooth vertical gradient
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # Cinema rule-of-thirds & framing guides
    guide_color = (255, 255, 255)
    for frac in (1 / 3, 2 / 3):
        gx = int(w * frac)
        gy = int(h * frac)
        draw.line([(gx, 40), (gx, h - 40)], fill=(95, 110, 145), width=1)
        draw.line([(40, gy), (w - 40, gy)], fill=(95, 110, 145), width=1)

    # Outer cinema frame
    margin = 36
    draw.rectangle([margin, margin, w - margin, h - margin], outline=(140, 155, 210), width=2)

    # Badge pill
    font_badge = _load_pil_font(22)
    font_title = _load_pil_font(42)
    font_sub = _load_pil_font(24)

    draw.rounded_rectangle([margin + 20, margin + 20, margin + 300, margin + 62], radius=8, fill=(99, 102, 241))
    draw.text((margin + 36, margin + 29), badge, fill=guide_color, font=font_badge)

    # Title & wrapped description
    center_y = int(h * 0.36)
    wrapped_title = textwrap.wrap(title.strip() or "Studio Frame", width=22)[:2]
    for i, line in enumerate(wrapped_title):
        draw.text((margin + 28, center_y + i * 54), line, fill=(245, 248, 255), font=font_title)

    wrapped_sub = textwrap.wrap(subtitle.strip(), width=42)[:5]
    sub_y = center_y + len(wrapped_title) * 54 + 22
    for i, line in enumerate(wrapped_sub):
        draw.text((margin + 28, sub_y + i * 34), line, fill=(203, 213, 225), font=font_sub)

    # Bottom metadata bar
    draw.text(
        (margin + 28, h - margin - 40),
        f"Aspect {aspect_ratio}  |  Local Demo Renderer (配置 GEMINI_API_KEY 后将使用 Nano Banana 2 真实渲染)",
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
    Generate an image with Nano Banana 2 (gemini-3.1-flash-image) or Demo Renderer.
    Returns (output_path, model_used, is_demo).
    """
    cfg = settings or load_settings()
    if cfg.effective_mode == "demo":
        render_demo_image(output_path, badge_title, prompt, aspect_ratio=aspect_ratio, badge="DEMO · NANO BANANA")
        return output_path, "demo-image", True

    from google.genai import types  # type: ignore

    client = _get_gemini_client(cfg)
    contents: list[Any] = []
    for ref_p in (reference_image_paths or [])[:6]:
        if ref_p and ref_p.exists():
            contents.append(Image.open(ref_p))
    contents.append(prompt)

    response = client.models.generate_content(
        model=cfg.image_model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
        ),
    )

    saved = False
    for candidate in getattr(response, "candidates", []) or []:
        parts = getattr(getattr(candidate, "content", None), "parts", []) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                img = Image.open(BytesIO(inline.data))
                output_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(output_path, format="PNG")
                saved = True
                break
        if saved:
            break

    if not saved:
        raise RuntimeError(f"模型 {cfg.image_model} 未返回图像数据，请检查提示词是否触发内容安全限制。")
    return output_path, cfg.image_model, False


def generate_video(
    engine: str,
    prompt_en: str,
    output_path: Path,
    duration_sec: int = 6,
    aspect_ratio: str = "16:9",
    start_frame_path: Path | None = None,
    end_frame_path: Path | None = None,
    reference_image_paths: list[Path] | None = None,
    with_audio: bool = True,
    badge_title: str = "Shot",
    on_progress: Callable[[int, str], None] | None = None,
    settings: RuntimeSettings | None = None,
) -> tuple[Path, str, bool]:
    """
    Generate video via Vertex AI Veo 3.1, Gemini API Omni 1.2 Flash, or local Demo FFmpeg renderer.
    Returns (output_path, model_used, is_demo).
    """
    cfg = settings or load_settings()
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
        return output_path, f"demo-{engine}", True

    # ---- Engine B: Gemini Omni 1.2 Flash (Gemini API Interactions API) ----
    if engine == "omni_flash":
        client = _get_gemini_client(cfg)
        if on_progress:
            on_progress(20, f"提交至 {cfg.omni_video_model} (Gemini Interactions API)...")

        input_payload: Any = prompt_en
        if start_frame_path and start_frame_path.exists():
            b64_img = base64.b64encode(start_frame_path.read_bytes()).decode("ascii")
            input_payload = [
                {"type": "image", "data": b64_img, "mime_type": "image/png"},
                {"type": "text", "text": f"Animate this keyframe into a {duration_sec}s {aspect_ratio} video with synchronized audio: {prompt_en}"},
            ]

        interaction = client.interactions.create(
            model=cfg.omni_video_model,
            input=input_payload,
        )
        if on_progress:
            on_progress(80, "解析返回视频流...")

        video_bytes = _extract_interaction_media_bytes(interaction, kind="video")
        if not video_bytes:
            raise RuntimeError(
                f"{cfg.omni_video_model} 未返回视频二进制内容（请确认当前 API Key 已开通该模型访问权限）。"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(video_bytes)
        return output_path, cfg.omni_video_model, False

    # ---- Engine A: Vertex AI Veo 3.1 (Lite / Fast / Standard) ----
    from google.genai import types  # type: ignore

    model_map = {
        "veo_lite": cfg.veo_lite_model,
        "veo_fast": cfg.veo_fast_model,
        "veo_standard": cfg.veo_standard_model,
    }
    model_id = model_map.get(engine, cfg.veo_lite_model)
    client = _get_vertex_client(cfg)

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

    return output_path, model_id, False


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

    client = _get_gemini_client(cfg)
    model_id = "lyria-3-pro-preview" if mode == "pro" else cfg.music_model
    interaction = client.interactions.create(model=model_id, input=prompt)
    audio_bytes = _extract_interaction_media_bytes(interaction, kind="audio")
    if not audio_bytes:
        raise RuntimeError(f"{model_id} 未返回音频数据，请检查模型权限或稍后重试。")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)
    return output_path, model_id, False


def _extract_interaction_media_bytes(interaction: Any, kind: str) -> bytes | None:
    attr_name = "output_audio" if kind == "audio" else "output_video"
    direct = getattr(interaction, attr_name, None)
    if direct and getattr(direct, "data", None):
        data = direct.data
        return base64.b64decode(data) if isinstance(data, str) else bytes(data)

    for out in getattr(interaction, "outputs", []) or []:
        otype = str(getattr(out, "type", "")).lower()
        mime = str(getattr(out, "mime_type", "")).lower()
        if kind in otype or kind in mime:
            data = getattr(out, "data", None)
            if data:
                return base64.b64decode(data) if isinstance(data, str) else bytes(data)
    return None


def review_video_qa(
    video_path: Path,
    shot_title: str,
    visual_prompt_zh: str,
    video_prompt_en: str,
    settings: RuntimeSettings | None = None,
) -> tuple[dict[str, Any], str, bool]:
    """Use Gemini multimodal video understanding to score and critique a generated take."""
    cfg = settings or load_settings()
    if cfg.effective_mode == "demo":
        return (
            {
                "score": 8,
                "summary": f"【Demo 审片】镜头「{shot_title}」画面构图稳定、节奏自然，与分镜描述吻合度较高。",
                "issues": ["Demo 模式下为模拟审片结果；填入 GEMINI_API_KEY 后将由 Gemini 真实逐帧看片质检"],
                "improved_prompt_en": f"{video_prompt_en}, cinematic 35mm lens, natural volumetric lighting, smooth motion continuity",
            },
            "demo-qa",
            True,
        )

    from google.genai import types  # type: ignore

    client = _get_gemini_client(cfg)
    video_bytes = video_path.read_bytes()
    prompt = (
        "你是专业影视后期与 AI 视频审片质检导演。请仔细观看这段视频，结合原分镜需求给出严格客观的评估。\n"
        f"- 镜头标题: {shot_title}\n"
        f"- 中文画面需求: {visual_prompt_zh}\n"
        f"- 英文生成提示词: {video_prompt_en}\n\n"
        "请严格输出 JSON 对象，包含以下字段：\n"
        '{"score": 1到10的整数, "summary": "简明中文总体评价(80字内)", "issues": ["发现的问题点列表"], "improved_prompt_en": "如果重拍，优化后的完整英文视频提示词"}'
    )
    response = client.models.generate_content(
        model=cfg.text_model,
        contents=[
            types.Part.from_bytes(data=video_bytes, mime_type="video/mp4"),
            prompt,
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    raw = (response.text or "{}").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"score": 7, "summary": raw[:120], "issues": [], "improved_prompt_en": video_prompt_en}
    return parsed, cfg.text_model, False
