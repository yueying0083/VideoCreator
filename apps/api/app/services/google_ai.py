from __future__ import annotations

import base64
from contextlib import ExitStack
import hashlib
import json
import textwrap
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import httpx
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from app.config import RuntimeSettings, load_settings
from app.services.genai_utils import (
    create_genai_client,
    detect_mime,
    extract_interaction_media,
    normalize_openai_base_url,
    sanitize_error,
    upload_file_to_gemini,
)
from app.services.media_renderer import aspect_to_dimensions, generate_demo_music, generate_demo_video
from app.services.task_runner import openai_image_limiter


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


def _map_openai_image_size(aspect_ratio: str, model_id: str) -> str:
    is_dalle3 = "dall-e-3" in (model_id or "").lower()
    if aspect_ratio == "16:9":
        return "1792x1024" if is_dalle3 else "1536x1024"
    if aspect_ratio == "9:16":
        return "1024x1792" if is_dalle3 else "1024x1536"
    return "1024x1024"


def generate_image_openai(
    prompt: str,
    output_path: Path,
    aspect_ratio: str = "16:9",
    reference_image_paths: list[Path] | None = None,
    on_progress: Callable[[int, str], None] | None = None,
    settings: RuntimeSettings | None = None,
) -> tuple[Path, str, bool]:
    """Generate or edit an image using OpenAI / GPT-Image compatible API with concurrency queuing."""
    cfg = settings or load_settings()
    api_key = cfg.openai_api_key.strip()
    if not api_key:
        raise RuntimeError(
            "已选择 GPT / OpenAI 生图引擎，但尚未填写 OPENAI_API_KEY。请在右上角「设置」中填入。"
        )

    base_url = normalize_openai_base_url(cfg.openai_base_url)
    model_id = cfg.openai_image_model.strip() or "gpt-image-1"
    size = _map_openai_image_size(aspect_ratio, model_id)
    ref_paths = [p for p in (reference_image_paths or []) if p and p.exists()][:6]

    def _on_wait(limit: int, pos: int) -> None:
        if on_progress:
            on_progress(15, f"排队等待 GPT 生图并发槽位（并发上限 {limit}，当前排第 {pos} 位）...")

    with openai_image_limiter.acquire(on_wait=_on_wait):
        if on_progress:
            on_progress(45, f"正在调用 GPT ({model_id}) 绘制图像...")

        try:
            headers = {"Authorization": f"Bearer {api_key}"}
            if ref_paths:
                with ExitStack() as stack:
                    if len(ref_paths) == 1:
                        rp = ref_paths[0]
                        fh = stack.enter_context(open(rp, "rb"))
                        files: Any = {"image": (rp.name, fh, detect_mime(rp, "image/png"))}
                    else:
                        files = [
                            ("image[]", (rp.name, stack.enter_context(open(rp, "rb")), detect_mime(rp, "image/png")))
                            for rp in ref_paths
                        ]
                    resp = httpx.post(
                        f"{base_url}/images/edits",
                        headers=headers,
                        data={"model": model_id, "prompt": prompt, "size": size},
                        files=files,
                        timeout=180.0,
                    )
            else:
                body: dict[str, Any] = {
                    "model": model_id,
                    "prompt": prompt,
                    "size": size,
                    "n": 1,
                }
                if "dall-e" in model_id.lower():
                    body["response_format"] = "b64_json"
                resp = httpx.post(
                    f"{base_url}/images/generations",
                    headers=headers,
                    json=body,
                    timeout=180.0,
                )

            if resp.status_code >= 400:
                raise RuntimeError(
                    f"GPT 生图接口错误（HTTP {resp.status_code}）：{sanitize_error(resp.text[:400], active_key=api_key)}"
                )

            payload = resp.json()
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"GPT 生图请求失败：{sanitize_error(exc, active_key=api_key)}")

    items = payload.get("data") or []
    if not items or not isinstance(items[0], dict):
        raise RuntimeError(f"模型 {model_id} 未返回图像数据。")

    first = items[0]
    img_bytes: bytes | None = None
    if first.get("b64_json"):
        img_bytes = base64.b64decode(first["b64_json"])
    elif first.get("url"):
        dl = httpx.get(str(first["url"]), timeout=120.0)
        if dl.status_code >= 400:
            raise RuntimeError(f"下载 GPT 生成图像失败（HTTP {dl.status_code}）")
        img_bytes = dl.content

    if not img_bytes:
        raise RuntimeError(f"模型 {model_id} 未返回有效的 b64_json 或图片 URL。")

    if on_progress:
        on_progress(85, "图像已生成，正在保存到本地...")

    img = Image.open(BytesIO(img_bytes))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="PNG")
    return output_path, model_id, False


def generate_image(
    prompt: str,
    output_path: Path,
    aspect_ratio: str = "16:9",
    reference_image_paths: list[Path] | None = None,
    badge_title: str = "Keyframe",
    purpose: str = "asset",
    on_progress: Callable[[int, str], None] | None = None,
    settings: RuntimeSettings | None = None,
) -> tuple[Path, str, bool]:
    """
    Generate an image via OpenAI GPT Image OR Gemini Nano Banana 2.1, or Demo Renderer.
    Supports up to 14 reference images for Gemini and multi-image edits for GPT.
    Returns (output_path, model_used, is_demo).
    """
    cfg = settings or load_settings()
    if cfg.effective_mode == "demo":
        badge = "DEMO · GPT IMAGE" if cfg.use_openai_for(purpose) else "DEMO · NANO BANANA"
        render_demo_image(output_path, badge_title, prompt, aspect_ratio=aspect_ratio, badge=badge)
        return output_path, "demo-image", True

    if cfg.use_openai_for(purpose):
        return generate_image_openai(
            prompt=prompt,
            output_path=output_path,
            aspect_ratio=aspect_ratio,
            reference_image_paths=reference_image_paths,
            on_progress=on_progress,
            settings=cfg,
        )

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
    ref_image_labels: list[str] | None = None,
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
    Generate video via Gemini Omni 1.2 Flash or Demo FFmpeg renderer.
    Returns (output_path, model_used, is_demo, interaction_id).
    """
    cfg = settings or load_settings()
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
        ref_image_labels=ref_image_labels,
        ref_video_asset_ids=ref_video_asset_ids,
        strip_audio=strip_audio or (not with_audio),
        previous_interaction_id=previous_interaction_id,
        task_override=task_override,
        badge_title=badge_title,
        on_status=_on_status,
        settings=cfg,
    )


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
