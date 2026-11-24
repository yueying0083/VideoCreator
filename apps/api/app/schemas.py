from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field


class SettingsOut(BaseModel):
    app_mode: Literal["auto", "live", "demo"]
    effective_mode: Literal["live", "demo"]
    has_gemini_key: bool
    gemini_api_key_masked: str
    has_vertex_config: bool
    vertex_project_id: str
    vertex_location: str
    google_application_credentials: str
    text_model: str
    image_model: str
    omni_video_model: str
    veo_lite_model: str
    veo_fast_model: str
    veo_standard_model: str
    music_model: str
    monthly_budget_usd: float
    ffmpeg_available: bool
    ffmpeg_path: str


class SettingsUpdate(BaseModel):
    app_mode: Literal["auto", "live", "demo"] | None = None
    gemini_api_key: str | None = None
    vertex_project_id: str | None = None
    vertex_location: str | None = None
    google_application_credentials: str | None = None
    text_model: str | None = None
    image_model: str | None = None
    omni_video_model: str | None = None
    veo_lite_model: str | None = None
    veo_fast_model: str | None = None
    veo_standard_model: str | None = None
    music_model: str | None = None
    monthly_budget_usd: float | None = None


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
    chars_per_episode: int = Field(default=2000, ge=300, le=20000)
    replace_existing: bool = True


class ExtractBibleRequest(BaseModel):
    max_episodes: int = Field(default=20, ge=1, le=200)


class EpisodeBreakdownRequest(BaseModel):
    target_shots: int = Field(default=6, ge=2, le=24)
    replace_existing: bool = True


class AssetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["character", "scene", "prop", "audio"] = "character"
    description: str = ""


class AssetUpdate(BaseModel):
    name: str | None = None
    kind: Literal["character", "scene", "prop", "audio"] | None = None
    description: str | None = None


class AssetGenerateRequest(BaseModel):
    prompt_override: str | None = None


class AssetOut(BaseModel):
    id: str
    project_id: str
    name: str
    kind: str
    description: str
    file_url: str | None = None
    turnaround_url: str | None = None
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
    has_audio: bool
    prompt_used: str
    qa_score: int | None = None
    qa_feedback: str | None = None
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


class VideoGenerateRequest(BaseModel):
    engine: Literal["veo_lite", "veo_fast", "veo_standard", "omni_flash"] = "veo_lite"
    duration_sec: int = 6
    with_audio: bool = True
    use_end_frame: bool = False
    prompt_override_en: str | None = None


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
    resolution: Literal["720p", "1080p"] = "1080p"
    include_bgm: bool = True
    burn_subtitles: bool = False


class ExportOut(BaseModel):
    id: str
    project_id: str
    file_url: str
    local_path: str
    resolution: str
    duration_sec: float
    include_bgm: bool
    burn_subtitles: bool
    created_at: datetime


class JobTaskOut(BaseModel):
    id: str
    project_id: str
    shot_id: str | None = None
    kind: str
    status: str
    progress: int
    message: str
    result: dict[str, Any] | None = None
    error: str | None = None
    estimated_cost_usd: float
    created_at: datetime
    updated_at: datetime
