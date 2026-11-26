"""Full Gemini Omni 1.2 Flash video engine & Gemini 4 prompt enhancer."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from google.genai import errors

from app.config import RuntimeSettings, load_settings
from app.database import Asset, SessionLocal
from app.schemas import EnhancePromptRequest, EnhancedPromptOutput
from app.services.genai_utils import (
    create_genai_client,
    detect_mime,
    extract_interaction_media,
    sanitize_error,
    upload_file_to_gemini,
)
from app.services.media_renderer import generate_demo_video, inspect_media

MIN_DURATION_SECONDS = 3
MAX_DURATION_SECONDS = 15
MAX_INTERPOLATION_OR_EXTEND_SECONDS = 10
MAX_REFERENCE_IMAGES = 6
MAX_REFERENCE_VIDEOS_SHORT = 3
MAX_REFERENCE_VIDEOS_LONG = 1
VALID_RESOLUTIONS = {"360p", "720p", "1080p", "4k"}
VALID_ASPECT_RATIOS = {"16:9", "9:16"}

OMNI_DIRECTOR_RULES = """You are an elite film director and prompt engineer specializing in Google's Gemini Omni 1.2 Flash video generation model.
Follow these strict Gemini Omni 1.2 Flash best practices:
1. Write the video generation prompt in vivid, natural, idiomatic English (Omni 1.2 Flash performs best in English).
2. NEVER use deprecated XML tags like <FIRST_FRAME>, <LAST_FRAME>, <IMAGE_REF_1>, or <VIDEO_REF_1>. Refer to assets naturally (e.g. "the woman from the first reference image", "Use the first image as the starting frame").
3. Omni Flash generates native synchronized audio (ambient sound, SFX, music, dialogue). Always craft intentional audio cues (or explicitly specify "No dialogue" when unwanted).
4. By default Omni Flash may introduce scene cuts. When a single unbroken shot is desired, explicitly include phrases like "Continuous, unbroken single shot, no scene cuts".
5. For editing prompts (mode='edit'), keep instructions concise and focused, ending with "Keep everything else the same" to preserve consistency.
6. For extension prompts (mode='extend'), begin naturally with continuation cues like "Extend this video seamlessly:" and specify whether the shot continues unbroken or cuts to a new angle.
7. When timecodes are requested for clips (3s-15s), use crisp bracketed segments like [0-4s] ... [4-8s] ... [8-12s] ... within the requested total duration.
8. Include concrete cinematography: lens/framing, camera motion, lighting mood, texture/micro-details, and realistic background activity."""


def validate_omni_request(
    *,
    mode: str,
    duration_seconds: int,
    aspect_ratio: str,
    resolution: str,
    has_first_frame: bool = False,
    has_last_frame: bool = False,
    has_source_video: bool = False,
    ref_image_count: int = 0,
    ref_video_count: int = 0,
    previous_interaction_id: str | None = None,
    task_override: str | None = None,
) -> None:
    """Validate parameter combinations strictly against Gemini Omni 1.2 Flash official constraints."""
    if aspect_ratio not in VALID_ASPECT_RATIOS:
        raise ValueError(f"Omni 1.2 Flash 仅支持 16:9 或 9:16 画幅，当前为：{aspect_ratio}。")
    if resolution.lower() not in VALID_RESOLUTIONS:
        raise ValueError(f"不支持的清晰度：{resolution}（支持 360p / 720p / 1080p / 4k）。")

    if not (MIN_DURATION_SECONDS <= duration_seconds <= MAX_DURATION_SECONDS):
        raise ValueError(f"视频时长需在 {MIN_DURATION_SECONDS} 到 {MAX_DURATION_SECONDS} 秒之间。")

    if has_last_frame and not has_first_frame:
        raise ValueError("指定尾帧时必须同时提供首帧图像。")

    if has_first_frame and has_last_frame and duration_seconds > MAX_INTERPOLATION_OR_EXTEND_SECONDS:
        raise ValueError(
            f"首尾帧过渡（First & Last Frame）时长上限为 {MAX_INTERPOLATION_OR_EXTEND_SECONDS} 秒，当前为 {duration_seconds} 秒。"
        )

    is_extend = mode == "extend" or task_override == "extend"
    is_edit = mode == "edit" or task_override == "edit"

    if is_extend and duration_seconds > MAX_INTERPOLATION_OR_EXTEND_SECONDS:
        raise ValueError(
            f"单次视频续写时长上限为 {MAX_INTERPOLATION_OR_EXTEND_SECONDS} 秒（累计最高 30 秒），当前为 {duration_seconds} 秒。"
        )

    if (is_edit or is_extend) and not has_source_video and not previous_interaction_id:
        raise ValueError("视频编辑或续写模式需要选择一个源视频素材，或基于已有生成结果发起多轮迭代。")

    if ref_image_count > MAX_REFERENCE_IMAGES:
        raise ValueError(f"最多支持 {MAX_REFERENCE_IMAGES} 张参考图，当前选择了 {ref_image_count} 张。")

    if ref_video_count > 0:
        if is_edit or is_extend or has_source_video or previous_interaction_id:
            raise ValueError(
                "参考视频（Video Reference）仅支持用于生成全新视频，不能与视频编辑、续写或多轮改片同时使用（参考图仍可正常使用）。"
            )
        max_vids = (
            MAX_REFERENCE_VIDEOS_LONG
            if duration_seconds > MAX_INTERPOLATION_OR_EXTEND_SECONDS
            else MAX_REFERENCE_VIDEOS_SHORT
        )
        if ref_video_count > max_vids:
            raise ValueError(
                f"{duration_seconds}s 视频最多支持 {max_vids} 段参考视频（3-10s 支持 3 段，11-15s 支持 1 段），当前选择了 {ref_video_count} 段。"
            )


def _append_role_hint(text: str, hint: str) -> str:
    clean = (text or "").strip()
    if not clean:
        return hint
    sep = "" if clean[-1] in ".!?。！？" else "."
    return f"{clean}{sep} {hint}"


def build_natural_language_prompt(
    *,
    prompt: str,
    mode: str,
    has_first_frame: bool,
    has_last_frame: bool,
    same_loop_frame: bool = False,
    ref_image_count: int = 0,
    ref_image_labels: list[str] | None = None,
    has_source_video: bool = False,
) -> str:
    """Attach clean natural-language media role bindings per Gemini Omni 1.2 Flash specification."""
    text = (prompt or "").strip()
    lower = text.lower()
    labels = [lbl.strip() for lbl in (ref_image_labels or []) if lbl and lbl.strip()]

    def _format_ref_bindings(start_idx: int) -> str:
        if not labels:
            return ""
        parts = [f"Image {start_idx + i} is {lbl}" for i, lbl in enumerate(labels)]
        return "; ".join(parts)

    if mode == "extend":
        if not any(tok in lower for tok in ("extend", "continue", "continuation", "keep going", "续写", "继续")):
            text = f"Extend this video seamlessly. {text}".strip()
        if labels:
            bindings = _format_ref_bindings(1)
            text = _append_role_hint(
                text,
                f"Use the attached reference image(s) for visual consistency ({bindings}).",
            )
    elif has_first_frame and has_last_frame:
        if same_loop_frame:
            if "starting frame" not in lower and "first frame" not in lower:
                ref_label = "the first image" if ref_image_count > 0 else "this image"
                text = _append_role_hint(
                    text,
                    f"Use {ref_label} as both the starting frame and the final frame to create a seamless loop.",
                )
        else:
            if "starting frame" not in lower and "first frame" not in lower:
                text = _append_role_hint(
                    text,
                    "Use the first image as the starting frame and the second image as the final frame.",
                )
        if ref_image_count > 0 and labels:
            bindings = _format_ref_bindings(3)
            text = _append_role_hint(
                text,
                f"Use the remaining images strictly as visual consistency references (not as scene cuts or collages): {bindings}.",
            )
    elif has_first_frame:
        if "starting frame" not in lower and "first frame" not in lower:
            ref_label = "the first image" if ref_image_count > 0 else "this image"
            text = _append_role_hint(text, f"Use {ref_label} as the starting frame.")
        if ref_image_count > 0 and labels:
            bindings = _format_ref_bindings(2)
            text = _append_role_hint(
                text,
                f"Use the remaining images strictly as visual consistency references (not as scene cuts or collages): {bindings}.",
            )
    elif ref_image_count > 0 and not has_source_video:
        if labels:
            bindings = _format_ref_bindings(1)
            text = _append_role_hint(
                text,
                f"Use these provided images strictly as visual character, prop, and environment references rather than literal starting frames or split-screen collages: {bindings}.",
            )
        elif "reference" not in lower and "参考" not in lower:
            text = _append_role_hint(
                text,
                "Use the provided image(s) as visual character, subject, and style references rather than literal starting frames.",
            )

    return text


def _upload_with_asset_cache(
    client: Any,
    path: Path,
    *,
    asset_id: str | None = None,
    strip_audio: bool = False,
    progress_cb: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    cached_uri = None
    cached_exp = None
    display_name = path.name
    mime_type = detect_mime(path)

    if asset_id:
        session = SessionLocal()
        try:
            asset = session.get(Asset, asset_id)
            if asset:
                display_name = asset.name or path.name
                mime_type = asset.mime_type or mime_type
                cached_uri = asset.gemini_file_uri
                cached_exp = asset.gemini_file_expires_at
        finally:
            session.close()

    uri, returned_mime, new_exp = upload_file_to_gemini(
        client,
        path,
        display_name=display_name,
        mime_type=mime_type,
        strip_audio=strip_audio,
        cached_uri=cached_uri,
        cached_expires_at=cached_exp,
        progress_cb=progress_cb,
    )

    if asset_id and not strip_audio and new_exp and (uri != cached_uri or new_exp != cached_exp):
        session = SessionLocal()
        try:
            asset = session.get(Asset, asset_id)
            if asset:
                asset.gemini_file_uri = uri
                asset.gemini_file_expires_at = new_exp
                session.commit()
        finally:
            session.close()

    return uri, returned_mime


def generate_omni_video(
    *,
    prompt_en: str,
    output_path: Path,
    mode: str = "text_to_video",
    duration_sec: int = 10,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    start_frame_path: Path | None = None,
    end_frame_path: Path | None = None,
    source_video_path: Path | None = None,
    ref_image_paths: list[Path] | None = None,
    ref_video_paths: list[Path] | None = None,
    first_frame_asset_id: str | None = None,
    last_frame_asset_id: str | None = None,
    source_video_asset_id: str | None = None,
    ref_image_asset_ids: list[str | None] | None = None,
    ref_image_labels: list[str] | None = None,
    ref_video_asset_ids: list[str | None] | None = None,
    strip_audio: bool = False,
    previous_interaction_id: str | None = None,
    task_override: str | None = None,
    badge_title: str = "Omni Shot",
    on_status: Callable[[str, int, str], None] | None = None,
    settings: RuntimeSettings | None = None,
) -> tuple[Path, str, bool, str | None]:
    """
    Execute a Gemini Omni 1.2 Flash video generation / edit / extend call.
    Returns (output_path, model_used, is_demo, interaction_id).
    """
    cfg = settings or load_settings()

    # Map unsupported 1:1 project ratio cleanly to 16:9 for Omni 1.2 Flash
    effective_ar = aspect_ratio if aspect_ratio in VALID_ASPECT_RATIOS else "16:9"
    effective_res = resolution.lower() if resolution.lower() in VALID_RESOLUTIONS else "720p"

    ref_imgs = [p for p in (ref_image_paths or []) if p and p.exists()]
    ref_vids = [p for p in (ref_video_paths or []) if p and p.exists()]
    has_first = bool(start_frame_path and start_frame_path.exists())
    has_last = bool(end_frame_path and end_frame_path.exists())
    has_source_vid = bool(source_video_path and source_video_path.exists())

    if cfg.effective_mode == "demo":
        from app.services.google_ai import render_demo_image

        if on_status:
            on_status("uploading", 25, "Demo 模式：准备输入素材与参数...")
        src_img = start_frame_path if has_first else None
        if not src_img:
            tmp_img = output_path.with_suffix(".tmp.png")
            render_demo_image(
                tmp_img,
                badge_title,
                prompt_en,
                aspect_ratio=effective_ar,
                badge=f"DEMO · OMNI {effective_res.upper()}",
            )
            src_img = tmp_img
        if on_status:
            on_status("generating", 60, f"Demo 模式：FFmpeg 模拟 Omni 1.2 Flash ({duration_sec}s · {effective_res})...")
        generate_demo_video(
            output_path,
            src_img,
            duration_sec=max(1, int(duration_sec)),
            aspect_ratio=effective_ar,
            with_audio=not strip_audio,
        )
        if not has_first and src_img.exists():
            src_img.unlink(missing_ok=True)
        demo_iid = f"demo_omni_{uuid.uuid4().hex[:10]}"
        return output_path, f"demo-{cfg.omni_video_model}", True, demo_iid

    validate_omni_request(
        mode=mode,
        duration_seconds=int(duration_sec),
        aspect_ratio=effective_ar,
        resolution=effective_res,
        has_first_frame=has_first,
        has_last_frame=has_last,
        has_source_video=has_source_vid,
        ref_image_count=len(ref_imgs),
        ref_video_count=len(ref_vids),
        previous_interaction_id=previous_interaction_id,
        task_override=task_override,
    )

    timeout_s = cfg.video_request_timeout
    if effective_res == "4k" or int(duration_sec) >= 12:
        timeout_s = max(timeout_s, 900)

    upload_client = create_genai_client(cfg, timeout_seconds=300)
    gen_client = create_genai_client(cfg, timeout_seconds=timeout_s)

    if on_status:
        on_status("uploading", 20, "正在上传并校验多模态输入素材...")

    def _upload_msg(msg: str) -> None:
        if on_status:
            on_status("uploading", 30, msg)

    input_parts: list[dict[str, Any]] = []

    # 1. First frame
    f1_uri: str | None = None
    f1_mime: str | None = None
    if has_first and start_frame_path is not None:
        f1_uri, f1_mime = _upload_with_asset_cache(
            upload_client,
            start_frame_path,
            asset_id=first_frame_asset_id,
            progress_cb=_upload_msg,
        )
        input_parts.append({"type": "image", "uri": f1_uri, "mime_type": f1_mime})

    # 2. Last frame (reuse URI if identical for seamless loop)
    same_loop = False
    if has_last and end_frame_path is not None:
        if (
            (last_frame_asset_id and first_frame_asset_id and last_frame_asset_id == first_frame_asset_id)
            or (start_frame_path and end_frame_path.resolve() == start_frame_path.resolve())
        ) and f1_uri and f1_mime:
            same_loop = True
            input_parts.append({"type": "image", "uri": f1_uri, "mime_type": f1_mime})
        else:
            f2_uri, f2_mime = _upload_with_asset_cache(
                upload_client,
                end_frame_path,
                asset_id=last_frame_asset_id,
                progress_cb=_upload_msg,
            )
            input_parts.append({"type": "image", "uri": f2_uri, "mime_type": f2_mime})

    # 3. Reference images (up to 6)
    img_ids = list(ref_image_asset_ids or [])
    for idx, img_path in enumerate(ref_imgs[:MAX_REFERENCE_IMAGES]):
        aid = img_ids[idx] if idx < len(img_ids) else None
        img_uri, img_mime = _upload_with_asset_cache(
            upload_client,
            img_path,
            asset_id=aid,
            progress_cb=_upload_msg,
        )
        input_parts.append({"type": "image", "uri": img_uri, "mime_type": img_mime})

    # 4. Source video (for edit / extend)
    if has_source_vid and source_video_path is not None:
        src_meta = inspect_media(source_video_path)
        src_dur = src_meta.get("duration_seconds")
        if src_dur and float(src_dur) > 15.5:
            raise ValueError(
                f"输入视频时长为 {float(src_dur):.1f}s，超过 Omni 1.2 Flash 的 15 秒上限。请先在「资产库」中一键裁剪至 10s 或 15s。"
            )
        vid_uri, vid_mime = _upload_with_asset_cache(
            upload_client,
            source_video_path,
            asset_id=source_video_asset_id,
            strip_audio=strip_audio,
            progress_cb=_upload_msg,
        )
        input_parts.append({"type": "video", "uri": vid_uri, "mime_type": vid_mime})

    # 5. Reference videos (only for new generation)
    vid_ids = list(ref_video_asset_ids or [])
    for idx, rv_path in enumerate(ref_vids):
        aid = vid_ids[idx] if idx < len(vid_ids) else None
        rv_uri, rv_mime = _upload_with_asset_cache(
            upload_client,
            rv_path,
            asset_id=aid,
            progress_cb=_upload_msg,
        )
        input_parts.append({"type": "video", "uri": rv_uri, "mime_type": rv_mime})

    # 6. Natural-language prompt
    final_prompt = build_natural_language_prompt(
        prompt=prompt_en,
        mode=mode,
        has_first_frame=has_first,
        has_last_frame=has_last,
        same_loop_frame=same_loop,
        ref_image_count=len(ref_imgs),
        ref_image_labels=(ref_image_labels[:MAX_REFERENCE_IMAGES] if ref_image_labels else None),
        has_source_video=bool(has_source_vid or previous_interaction_id),
    )
    input_parts.append({"type": "text", "text": final_prompt})

    response_format: dict[str, Any] = {
        "type": "video",
        "delivery": "uri",
        "duration": f"{int(duration_sec)}s",
        "resolution": effective_res,
    }
    if task_override != "extend":
        response_format["aspect_ratio"] = effective_ar

    create_kwargs: dict[str, Any] = {
        "model": cfg.omni_video_model,
        "input": input_parts,
        "response_format": response_format,
    }
    if task_override and not previous_interaction_id:
        create_kwargs["generation_config"] = {"video_config": {"task": task_override}}
    if previous_interaction_id:
        create_kwargs["previous_interaction_id"] = previous_interaction_id

    if on_status:
        on_status(
            "generating",
            55,
            f"正在调用 {cfg.omni_video_model} 生成 {duration_sec}s · {effective_res.upper()} ({effective_ar}) 视频...",
        )

    try:
        interaction = gen_client.interactions.create(**create_kwargs)
    except errors.APIError as e:
        raise RuntimeError(f"Gemini Omni API 错误：{sanitize_error(e)}")
    except Exception as e:
        raise RuntimeError(f"调用视频生成失败：{sanitize_error(e)}")

    interaction_id = getattr(interaction, "id", None)

    if on_status:
        on_status("downloading", 85, "视频生成完成，正在下载到本地并生成缩略图...")

    video_bytes = extract_interaction_media(gen_client, interaction, "video")
    if not video_bytes:
        hint = ""
        if has_source_vid or ref_vids:
            hint = "（提示：若在欧洲经济区/英国/瑞士或部分受限地区，上传外部视频进行编辑或参考可能受区域策略限制；此外请确认提示词未触发安全过滤。）"
        raise RuntimeError(f"模型未返回视频输出内容。{hint}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(video_bytes)
    return output_path, cfg.omni_video_model, False, interaction_id


def enhance_omni_prompt(
    req: EnhancePromptRequest,
    settings: RuntimeSettings | None = None,
) -> tuple[EnhancedPromptOutput, str, bool]:
    """Use Gemini 4 via Interactions API + Structured Output to optimize a Gemini Omni 1.2 Flash prompt."""
    cfg = settings or load_settings()
    if cfg.effective_mode == "demo":
        base = req.prompt.strip()
        single_phrase = "Continuous, unbroken single shot, no scene cuts. " if req.single_scene else ""
        tc_phrase = (
            f"[0-{max(2, req.duration_seconds // 2)}s] Establishing visual motion. "
            f"[{max(2, req.duration_seconds // 2)}-{req.duration_seconds}s] Dynamic payoff and atmospheric finish. "
            if req.include_timecodes
            else ""
        )
        audio_line = req.audio_preference or "Rich natural ambient soundscape and subtle cinematic underscore, no unwanted dialogue."
        out = EnhancedPromptOutput(
            enhanced_prompt_en=(
                f"{single_phrase}{tc_phrase}Cinematic {req.aspect_ratio} sequence: {base}. "
                f"35mm anamorphic lens, realistic textures, natural volumetric lighting, lived-in background motion. "
                f"Sound design: {audio_line}"
            ),
            summary_zh=f"【Demo 导演扩写】已将「{base[:36]}」优化为适合 Gemini Omni 1.2 Flash 的 {req.duration_seconds}s 电影级英文提示词。",
            audio_cue=audio_line,
            camera_notes="35mm 电影镜头，平滑稳定器推进，自然体积光与浅景深",
            tips=[
                "如需严格一镜到底防切镜，请保持「一镜到底」开关开启",
                "可搭配 1~6 张参考图锁定角色服装与场景美术风格",
            ],
        )
        return out, "demo-gemini-4", True

    model_id = req.model or cfg.text_model
    client = create_genai_client(cfg, timeout_seconds=90)

    context_lines = [
        f"- Mode: {req.mode}",
        f"- Target Duration: {req.duration_seconds} seconds",
        f"- Aspect Ratio: {req.aspect_ratio}",
        f"- Single Unbroken Scene (no cuts): {'YES - enforce single continuous shot' if req.single_scene else 'NO - natural pacing allowed'}",
        f"- Bracketed Timecode Beats: {'YES - break into [0-Xs] segments covering 0 to ' + str(req.duration_seconds) + 's' if req.include_timecodes else 'NO'}",
        f"- Attached First Frame: {'YES' if req.has_first_frame else 'NO'}",
        f"- Attached Last Frame: {'YES' if req.has_last_frame else 'NO'}",
        f"- Attached Reference Images: {req.ref_image_count}",
        f"- Attached Reference Videos: {req.ref_video_count}",
    ]
    if req.style_hint:
        context_lines.append(f"- Desired Visual Style: {req.style_hint}")
    if req.audio_preference:
        context_lines.append(f"- Audio Preference: {req.audio_preference}")

    user_prompt = (
        "Transform the user's raw idea below into an optimal Gemini Omni 1.2 Flash prompt.\n\n"
        "Parameters:\n"
        + "\n".join(context_lines)
        + f"\n\nUser raw prompt:\n{req.prompt.strip()}"
    )

    try:
        interaction = client.interactions.create(
            model=model_id,
            system_instruction=OMNI_DIRECTOR_RULES,
            input=user_prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": EnhancedPromptOutput.model_json_schema(),
            },
            store=False,
        )
    except errors.APIError as e:
        raise RuntimeError(f"AI 导演提示词优化失败：{sanitize_error(e)}")
    except Exception as e:
        raise RuntimeError(f"AI 导演提示词优化失败：{sanitize_error(e)}")

    raw_text = interaction.output_text
    if not raw_text:
        raise RuntimeError("AI 导演未返回有效结构化文本，请重试。")

    return EnhancedPromptOutput.model_validate_json(raw_text), model_id, False
