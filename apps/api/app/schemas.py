from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

DialogueMode = Literal["spoken", "narration", "none"]


class SettingsOut(BaseModel):
    app_mode: Literal["auto", "live", "demo"]
    effective_mode: Literal["live", "demo"]
    has_gemini_key: bool
    gemini_api_key_masked: str
    image_provider: Literal["gemini", "openai_assets", "openai_all"]
    has_openai_key: bool
    openai_base_url: str
    openai_api_key_masked: str
    openai_image_model: str
    openai_max_concurrent: int
    text_model: str
    image_model: str
    omni_video_model: str
    music_model: str
    max_concurrent_jobs: int
    video_request_timeout: int
    monthly_budget_usd: float
    ffmpeg_available: bool
    ffprobe_available: bool
    ffmpeg_path: str


class SettingsUpdate(BaseModel):
    app_mode: Literal["auto", "live", "demo"] | None = None
    gemini_api_key: str | None = None
    image_provider: Literal["gemini", "openai_assets", "openai_all"] | None = None
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_image_model: str | None = None
    openai_max_concurrent: int | None = Field(default=None, ge=1, le=8)
    text_model: str | None = None
    image_model: str | None = None
    omni_video_model: str | None = None
    music_model: str | None = None
    max_concurrent_jobs: int | None = Field(default=None, ge=1, le=6)
    video_request_timeout: int | None = Field(default=None, ge=120, le=1800)
    monthly_budget_usd: float | None = None


class ConnectionTestRequest(BaseModel):
    gemini_api_key: str | None = None


class OpenAIConnectionTestRequest(BaseModel):
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_image_model: str | None = None


class ConnectionTestResponse(BaseModel):
    ok: bool
    message: str
    checked_model: str | None = None


class BudgetSummary(BaseModel):
    month: str
    spent_usd: float
    demo_simulated_usd: float
    monthly_budget_usd: float
    remaining_usd: float
    percent_used: float


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    style_prompt: str = "电影质感，自然光影，高细节写实摄影"


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    aspect_ratio: Literal["16:9", "9:16", "1:1"] | None = None
    style_prompt: str | None = None
    bgm_volume: float | None = None
    subtitle_srt: str | None = None


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    aspect_ratio: str
    style_prompt: str
    bgm_url: str | None = None
    bgm_prompt: str = ""
    bgm_volume: float = 0.25
    subtitle_srt: str = ""
    novel_title: str = ""
    shot_count: int = 0
    asset_count: int = 0
    episode_count: int = 0
    created_at: datetime
    updated_at: datetime


class EpisodeOut(BaseModel):
    id: str
    project_id: str
    order_index: int
    title: str
    source_text: str
    char_count: int
    summary: str
    target_shots: int
    status: str
    shot_count: int = 0
    created_at: datetime


class EpisodeUpdate(BaseModel):
    title: str | None = None
    source_text: str | None = None
    summary: str | None = None
    target_shots: int | None = None


class NovelImportTextRequest(BaseModel):
    novel_title: str = "导入小说"
    text: str = Field(min_length=10)
    split_mode: Literal["auto_chapter", "by_length"] = "auto_chapter"
    chars_per_episode: int = Field(default=1200, ge=300, le=20000)
    replace_existing: bool = True


class ExtractBibleRequest(BaseModel):
    max_episodes: int = Field(default=20, ge=1, le=200)


class EpisodeBreakdownRequest(BaseModel):
    target_shots: int = Field(default=10, ge=2, le=40)
    replace_existing: bool = True


class AssetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["character", "scene", "prop", "audio", "video"] = "character"
    description: str = ""


class AssetUpdate(BaseModel):
    name: str | None = None
    kind: Literal["character", "scene", "prop", "audio", "video"] | None = None
    description: str | None = None


class AssetGenerateRequest(BaseModel):
    prompt_override: str | None = None


class BatchGenerateAssetsRequest(BaseModel):
    asset_ids: list[str] = Field(min_length=1)
    target: Literal["portrait", "turnaround", "both"] = "portrait"
    regenerate: bool = False


class BatchGenerateAssetsResponse(BaseModel):
    submitted_count: int
    skipped_count: int
    tasks: list["JobTaskOut"] = Field(default_factory=list)


class PrepAssetRequest(BaseModel):
    start_seconds: float = Field(default=0.0, ge=0.0)
    duration: int = Field(default=10, ge=1, le=15)
    strip_audio: bool = False
    max_edge: int = Field(default=1280, ge=360, le=3840)


class ExtractFrameRequest(BaseModel):
    position: Literal["first", "last", "custom"] = "last"
    timestamp_seconds: float | None = Field(default=None, ge=0.0)


class AssetOut(BaseModel):
    id: str
    project_id: str
    name: str
    kind: str
    description: str
    file_url: str | None = None
    turnaround_url: str | None = None
    media_type: str = "image"
    mime_type: str = ""
    thumb_url: str | None = None
    size_bytes: int = 0
    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None
    fps: str | None = None
    has_audio: bool = False
    created_at: datetime


class TakeOut(BaseModel):
    id: str
    shot_id: str
    project_id: str
    engine: str
    model_id: str
    file_url: str
    thumbnail_url: str | None = None
    duration_sec: float
    resolution: str = "720p"
    has_audio: bool
    prompt_used: str
    interaction_id: str | None = None
    parent_take_id: str | None = None
    mode: str = "generate"
    qa_score: int | None = None
    qa_feedback: str | None = None
    qa_improved_prompt: str | None = None
    cost_usd: float
    created_at: datetime


class ShotCreate(BaseModel):
    episode_id: str | None = None
    title: str = "新镜头"
    shot_type: str = "中景"
    camera_movement: str = "缓慢推进"
    visual_prompt_zh: str = ""
    video_prompt_en: str = ""
    dialogue: str = ""
    dialogue_mode: DialogueMode = "spoken"
    sfx_prompt: str = ""
    duration_sec: int = 6
    asset_ids: list[str] = Field(default_factory=list)


class ShotUpdate(BaseModel):
    episode_id: str | None = None
    order_index: int | None = None
    title: str | None = None
    shot_type: str | None = None
    camera_movement: str | None = None
    visual_prompt_zh: str | None = None
    video_prompt_en: str | None = None
    dialogue: str | None = None
    dialogue_mode: DialogueMode | None = None
    sfx_prompt: str | None = None
    duration_sec: int | None = None
    asset_ids: list[str] | None = None
    selected_take_id: str | None = None
    trim_start: float | None = None
    trim_end: float | None = None


class ShotOut(BaseModel):
    id: str
    project_id: str
    episode_id: str | None = None
    order_index: int
    title: str
    shot_type: str
    camera_movement: str
    visual_prompt_zh: str
    video_prompt_en: str
    dialogue: str
    dialogue_mode: DialogueMode = "spoken"
    sfx_prompt: str
    duration_sec: int
    asset_ids: list[str] = Field(default_factory=list)
    start_frame_url: str | None = None
    end_frame_url: str | None = None
    start_frame_local_path: str | None = None
    end_frame_local_path: str | None = None
    selected_take_id: str | None = None
    trim_start: float = 0.0
    trim_end: float | None = None
    takes: list[TakeOut] = Field(default_factory=list)
    created_at: datetime


class KeyframeGenerateRequest(BaseModel):
    which: Literal["start", "end"] = "start"
    prompt_override: str | None = None


class BatchGenerateKeyframesRequest(BaseModel):
    episode_id: str | None = None
    which: Literal["start", "end"] = "start"
    only_missing: bool = True


class BatchGenerateKeyframesResponse(BaseModel):
    submitted_count: int
    skipped_count: int
    tasks: list["JobTaskOut"] = Field(default_factory=list)


class VideoGenerateRequest(BaseModel):
    engine: Literal["omni_flash"] = "omni_flash"
    duration_sec: int = Field(default=6, ge=1, le=15)
    resolution: Literal["360p", "720p", "1080p", "4k"] = "720p"
    with_audio: bool = True
    use_end_frame: bool = False
    use_asset_refs_with_start_frame: bool = False
    prompt_override_en: str | None = None


class BatchGenerateShotsRequest(BaseModel):
    episode_id: str | None = None
    engine: Literal["omni_flash"] = "omni_flash"
    resolution: Literal["360p", "720p", "1080p", "4k"] = "720p"
    with_audio: bool = True
    use_end_frame: bool = False
    use_asset_refs_with_start_frame: bool = False
    only_pending: bool = True
    chain_last_frame: bool = False


class IterateTakeRequest(BaseModel):
    action: Literal["edit", "extend"] = "edit"
    prompt: str = Field(..., min_length=1, max_length=4000)
    duration_sec: int = Field(default=6, ge=3, le=15)
    resolution: Literal["360p", "720p", "1080p", "4k"] = "720p"
    strip_audio: bool = False
    ref_asset_ids: list[str] = Field(default_factory=list)


class EnhancePromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=3000)
    mode: str = "text_to_video"
    duration_seconds: int = Field(default=10, ge=3, le=15)
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"
    single_scene: bool = False
    include_timecodes: bool = False
    audio_preference: str | None = None
    style_hint: str | None = None
    has_first_frame: bool = False
    has_last_frame: bool = False
    ref_image_count: int = 0
    ref_video_count: int = 0
    model: str | None = None


class EnhancedPromptOutput(BaseModel):
    """Structured output returned by Gemini 4 for Omni Flash prompt optimization."""

    enhanced_prompt_en: str = Field(
        description=(
            "Production-ready English prompt optimized specifically for Gemini Omni 1.2 Flash. "
            "Includes visual detail, camera movement, lighting, pacing, and sound design."
        )
    )
    summary_zh: str = Field(
        description="Concise Chinese explanation of what the enhanced prompt will produce."
    )
    audio_cue: str = Field(
        description="Summary of the soundscape, music, dialogue, or ambient audio cue included."
    )
    camera_notes: str = Field(
        description="Brief camera & composition breakdown (lens, movement, framing)."
    )
    tips: list[str] = Field(
        default_factory=list,
        description="1 to 3 practical creative tips in Chinese for iterating on this shot.",
    )


StudioJobMode = Literal[
    "text_to_video",
    "first_frame",
    "first_last_frame",
    "reference_to_video",
    "edit",
    "extend",
]


class StudioJobCreateRequest(BaseModel):
    mode: StudioJobMode = "text_to_video"
    prompt: str = Field(..., min_length=1, max_length=4000)
    enhanced_prompt: str | None = None
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"
    duration_seconds: int = Field(default=10, ge=3, le=15)
    resolution: Literal["360p", "720p", "1080p", "4k"] = "720p"
    strip_audio: bool = False
    task_override: Literal["text_to_video", "image_to_video", "reference_to_video", "edit", "extend"] | None = None
    first_frame_asset_id: str | None = None
    last_frame_asset_id: str | None = None
    source_video_asset_id: str | None = None
    ref_image_asset_ids: list[str] = Field(default_factory=list)
    ref_video_asset_ids: list[str] = Field(default_factory=list)
    parent_job_id: str | None = None
    previous_interaction_id: str | None = None


class StudioJobOut(BaseModel):
    id: str
    project_id: str
    mode: str
    status: str
    progress: int = 0
    progress_message: str = ""
    prompt: str
    enhanced_prompt: str | None = None
    model: str
    aspect_ratio: str
    duration_seconds: int
    resolution: str
    strip_audio: bool = False
    task_override: str | None = None
    first_frame_asset_id: str | None = None
    last_frame_asset_id: str | None = None
    source_video_asset_id: str | None = None
    ref_image_asset_ids: list[str] = Field(default_factory=list)
    ref_video_asset_ids: list[str] = Field(default_factory=list)
    parent_job_id: str | None = None
    previous_interaction_id: str | None = None
    interaction_id: str | None = None
    output_url: str | None = None
    output_thumb_url: str | None = None
    output_duration_seconds: float | None = None
    output_width: int | None = None
    output_height: int | None = None
    output_has_audio: bool = True
    output_size_bytes: int | None = None
    cost_usd: float = 0.0
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class ChatSendRequest(BaseModel):
    content: str = Field(min_length=1)


class ChatMessageOut(BaseModel):
    id: str
    project_id: str
    role: str
    content: str
    proposal: dict[str, Any] | None = None
    proposal_applied: bool = False
    created_at: datetime


class MusicGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    mode: Literal["clip", "pro"] = "clip"


class ExportRequest(BaseModel):
    episode_id: str | None = None
    resolution: Literal["720p", "1080p", "4k"] = "1080p"
    crossfade_sec: float = Field(default=0.0, ge=0.0, le=1.5)
    include_bgm: bool = True
    burn_subtitles: bool = False


class ExportOut(BaseModel):
    id: str
    project_id: str
    file_url: str
    local_path: str
    resolution: str
    duration_sec: float
    crossfade_sec: float = 0.0
    include_bgm: bool
    burn_subtitles: bool
    created_at: datetime


class JobTaskOut(BaseModel):
    id: str
    project_id: str
    shot_id: str | None = None
    asset_id: str | None = None
    kind: str
    status: str
    progress: int
    message: str
    result: dict[str, Any] | None = None
    error: str | None = None
    estimated_cost_usd: float
    created_at: datetime
    updated_at: datetime


class AuthStatusOut(BaseModel):
    auth_enabled: bool
    initialized: bool
    authenticated: bool
    username: str | None = None
    role: str | None = None


class AuthSetupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)


class AuthLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
    remember: bool = True


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)
