"""Official google-genai SDK client helpers, Files API caching, media extraction, and secret-safe error sanitizer."""

from __future__ import annotations

import base64
import mimetypes
import re
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from google import genai
from google.genai import errors, types

from app.config import DATA_DIR, RuntimeSettings, load_settings


def require_gemini_key(settings: RuntimeSettings | None = None, override_key: str | None = None) -> str:
    cfg = settings or load_settings()
    key = (override_key if override_key is not None else cfg.gemini_api_key or "").strip()
    if not key:
        raise RuntimeError(
            "尚未配置 GEMINI_API_KEY。请在根目录 .env 或右上角「设置」中填写你的 Google AI Studio API Key。"
        )
    return key


def create_genai_client(
    settings: RuntimeSettings | None = None,
    *,
    timeout_seconds: int = 120,
    api_key_override: str | None = None,
) -> genai.Client:
    key = require_gemini_key(settings, api_key_override)
    return genai.Client(
        api_key=key,
        http_options=types.HttpOptions(timeout=int(timeout_seconds) * 1000),
    )


def create_vertex_client(settings: RuntimeSettings | None = None) -> genai.Client:
    cfg = settings or load_settings()
    if not cfg.vertex_project_id:
        raise RuntimeError(
            "调用 Veo 3.1 正式版需要配置 Vertex AI（VERTEX_PROJECT_ID）。"
            "请在「设置」中配置 GCP 项目，或将视频引擎切换为 Gemini Omni 1.2 Flash（仅需 GEMINI_API_KEY），"
            "或点击「复制 Flow 创作包」使用 Google Flow 网页端 25,000 Ultra 积分生成。"
        )
    return genai.Client(
        vertexai=True,
        project=cfg.vertex_project_id,
        location=cfg.vertex_location or "us-central1",
    )


def sanitize_error(err: Exception | str | None, active_key: str | None = None) -> str:
    """Redact API keys, tokens, sensitive query params, and internal endpoints from error text."""
    if not err:
        return ""

    if isinstance(err, errors.APIError):
        parts: list[str] = []
        if getattr(err, "code", None):
            parts.append(str(err.code))
        if getattr(err, "status", None):
            parts.append(f"({err.status})")
        if getattr(err, "message", None):
            parts.append(f": {err.message}")
        elif getattr(err, "details", None):
            parts.append(f": {err.details}")
        err_str = " ".join(parts) if parts else str(err)
    else:
        err_str = str(err)

    key = (active_key or load_settings().gemini_api_key or "").strip()
    if key and len(key) >= 8:
        err_str = err_str.replace(key, "[REDACTED_KEY]")

    err_str = re.sub(r"AIza[0-9A-Za-z_\-]{25,}", "[REDACTED_KEY]", err_str)
    err_str = re.sub(r"AQ\.[0-9A-Za-z_\-]{20,}", "[REDACTED_KEY]", err_str)
    err_str = re.sub(r"ya29\.[0-9A-Za-z_\-]+", "[REDACTED_TOKEN]", err_str)
    err_str = re.sub(
        r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [REDACTED_TOKEN]", err_str, flags=re.IGNORECASE
    )
    err_str = re.sub(
        r"([?&](?:key|api_key|apiKey|access_token|auth|signature)=)[^&\s\"'<>()]+",
        r"\1[REDACTED]",
        err_str,
    )
    err_str = re.sub(
        r"https?://[a-zA-Z0-9.\-_]*\.corp\.goog[^\s\"'<>)]*", "[INTERNAL_HOST]", err_str
    )
    err_str = re.sub(
        r"https?://[a-zA-Z0-9.\-_]*\.sandbox\.googleapis\.com[^\s\"'<>)]*",
        "[SANDBOX_ENDPOINT]",
        err_str,
    )
    err_str = re.sub(
        r"\bbody\s*=.*\Z", "body=[REDACTED_BODY]", err_str, flags=re.IGNORECASE | re.DOTALL
    )
    err_str = re.sub(r"\s+", " ", err_str).strip()
    if len(err_str) > 600:
        err_str = err_str[:597] + "..."
    return err_str


def test_gemini_connection(
    settings: RuntimeSettings | None = None,
    api_key_override: str | None = None,
) -> tuple[bool, str, str | None]:
    """Validate API key connectivity by querying model metadata via google-genai SDK."""
    cfg = settings or load_settings()
    cleaned_override = (api_key_override or "").strip()
    if cleaned_override.startswith("••••"):
        cleaned_override = ""
    effective_key = cleaned_override or cfg.gemini_api_key

    try:
        client = create_genai_client(cfg, timeout_seconds=20, api_key_override=effective_key)
        model_info = client.models.get(model=cfg.omni_video_model)
        name = getattr(model_info, "name", None) or cfg.omni_video_model
        return True, f"连接成功！已验证可用模型：{name}", name
    except Exception as e:
        try:
            client = create_genai_client(cfg, timeout_seconds=20, api_key_override=effective_key)
            model_info = client.models.get(model=cfg.text_model)
            name = getattr(model_info, "name", None) or cfg.text_model
            return True, f"API Key 有效（已连接 {name}）。", name
        except Exception as inner:
            return False, f"连接测试失败：{sanitize_error(inner or e, active_key=effective_key)}", None


def _strip_query(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(parsed._replace(query=""))


def normalize_file_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    m = re.search(r"files/([a-zA-Z0-9_-]+)", uri)
    if m:
        return f"https://generativelanguage.googleapis.com/files/{m.group(1)}"
    return _strip_query(uri)


def extract_file_name(uri: str) -> str | None:
    m = re.search(r"(files/[a-zA-Z0-9_-]+)", uri)
    return m.group(1) if m else None


def detect_mime(file_path: Path, fallback: str = "application/octet-stream") -> str:
    ext_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
        ".m4v": "video/mp4",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
    }
    ext = file_path.suffix.lower()
    if ext in ext_map:
        return ext_map[ext]
    guessed, _ = mimetypes.guess_type(str(file_path))
    return guessed or fallback


def is_cached_uri_valid(uri: str | None, expires_at: str | None) -> bool:
    if not uri or not expires_at:
        return False
    try:
        exp_dt = datetime.fromisoformat(expires_at)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < exp_dt
    except ValueError:
        return False


def wait_file_active(client: Any, file_name: str, max_timeout: int = 420) -> Any:
    interval = 2.5
    started = time.time()
    consecutive_errors = 0
    while True:
        if time.time() - started > max_timeout:
            raise TimeoutError(f"等待 Gemini Files API 文件 {file_name} 激活超时。")
        try:
            f_obj = client.files.get(name=file_name)
            consecutive_errors = 0
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors >= 5:
                raise RuntimeError(f"查询文件处理状态失败：{sanitize_error(e)}")
            time.sleep(interval)
            interval = min(interval * 1.25, 12.0)
            continue

        state = getattr(f_obj, "state", None)
        state_str = state.name if hasattr(state, "name") else str(state)
        if state == types.FileState.ACTIVE or state_str == "ACTIVE":
            return f_obj
        if state == types.FileState.FAILED or state_str == "FAILED":
            err = getattr(f_obj, "error", None)
            raise RuntimeError(f"Google Files API 文件处理失败：{sanitize_error(err or state_str)}")

        time.sleep(interval)
        interval = min(interval * 1.2, 12.0)


def upload_file_to_gemini(
    client: Any,
    local_path: Path,
    *,
    display_name: str | None = None,
    mime_type: str | None = None,
    strip_audio: bool = False,
    cached_uri: str | None = None,
    cached_expires_at: str | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> tuple[str, str, str | None]:
    """Upload a local media file to Gemini Files API with 40h URI caching & optional audio stripping."""
    if not local_path.exists():
        raise FileNotFoundError(f"本地素材文件不存在：{local_path}")

    resolved_mime = mime_type or detect_mime(local_path)
    if not strip_audio and is_cached_uri_valid(cached_uri, cached_expires_at):
        return cached_uri, resolved_mime, cached_expires_at  # type: ignore[return-value]

    temp_stripped: Path | None = None
    upload_path = local_path
    label = display_name or local_path.name

    try:
        if strip_audio:
            from app.services.media_renderer import strip_audio_fast

            if progress_cb:
                progress_cb(f"正在剥离原声轨（以便重配全套音频）：{label}...")
            temp_dir = DATA_DIR / "temp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_stripped = temp_dir / f"stripped_{uuid.uuid4().hex}{local_path.suffix or '.mp4'}"
            strip_audio_fast(local_path, temp_stripped)
            upload_path = temp_stripped

        if progress_cb:
            progress_cb(f"正在上传素材到 Gemini Files API：{label}...")

        f_obj = client.files.upload(
            file=str(upload_path),
            config=types.UploadFileConfig(
                display_name=label,
                mime_type=resolved_mime,
            ),
        )
        file_name = getattr(f_obj, "name", None)
        if file_name:
            f_obj = wait_file_active(client, file_name)

        uri = normalize_file_uri(getattr(f_obj, "uri", None))
        if not uri:
            raise RuntimeError(f"素材上传未返回有效 URI：{label}")

        returned_mime = getattr(f_obj, "mime_type", None) or resolved_mime
        new_exp = None
        if not strip_audio:
            new_exp = (datetime.now(timezone.utc) + timedelta(hours=40)).isoformat()

        return uri, returned_mime, new_exp
    finally:
        if temp_stripped and temp_stripped.exists():
            try:
                temp_stripped.unlink()
            except OSError:
                pass


def extract_interaction_media(
    client: Any,
    interaction: Any,
    kind: Literal["image", "audio", "video"],
) -> bytes | None:
    """Extract binary media from an Interaction via output_* helpers, steps[], or URI download."""
    attr_name = f"output_{kind}"
    candidates: list[Any] = []

    direct = getattr(interaction, attr_name, None)
    if direct is not None:
        candidates.append(direct)

    for step in getattr(interaction, "steps", []) or []:
        if getattr(step, "type", None) == "model_output":
            for item in getattr(step, "content", []) or []:
                itype = str(getattr(item, "type", "")).lower()
                mime = str(getattr(item, "mime_type", "")).lower()
                if itype == kind or kind in mime:
                    candidates.append(item)

    for out in getattr(interaction, "outputs", []) or []:
        otype = str(getattr(out, "type", "")).lower()
        mime = str(getattr(out, "mime_type", "")).lower()
        if kind in otype or kind in mime:
            candidates.append(out)

    for item in candidates:
        uri = getattr(item, "uri", None)
        data = getattr(item, "data", None)
        if uri:
            file_name = extract_file_name(uri)
            if file_name and kind == "video":
                try:
                    wait_file_active(client, file_name, max_timeout=240)
                except Exception:
                    pass
            try:
                downloaded = client.files.download(file=uri)
                if downloaded:
                    return bytes(downloaded)
            except Exception as exc:
                if not data:
                    raise RuntimeError(f"下载生成媒体失败：{sanitize_error(exc)}")
        if data:
            return base64.b64decode(data) if isinstance(data, str) else bytes(data)

    return None
