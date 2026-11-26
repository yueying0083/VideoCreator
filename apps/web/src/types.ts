export type AppMode = "auto" | "live" | "demo";
export type ImageProvider = "gemini" | "openai_assets" | "openai_all";
export type DialogueMode = "spoken" | "narration" | "none";
export type VideoEngine = "omni_flash";
export type VideoResolution = "360p" | "720p" | "1080p" | "4k";

export interface Settings {
  app_mode: AppMode;
  effective_mode: "live" | "demo";
  has_gemini_key: boolean;
  gemini_api_key_masked: string;
  image_provider: ImageProvider;
  has_openai_key: boolean;
  openai_base_url: string;
  openai_api_key_masked: string;
  openai_image_model: string;
  openai_max_concurrent: number;
  text_model: string;
  image_model: string;
  omni_video_model: string;
  music_model: string;
  max_concurrent_jobs: number;
  video_request_timeout: number;
  monthly_budget_usd: number;
  ffmpeg_available: boolean;
  ffprobe_available: boolean;
  ffmpeg_path: string;
}

export interface ConnectionTestResult {
  ok: boolean;
  message: string;
  checked_model: string | null;
}

export interface BudgetSummary {
  month: string;
  spent_usd: number;
  demo_simulated_usd: number;
  monthly_budget_usd: number;
  remaining_usd: number;
  percent_used: number;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  aspect_ratio: "16:9" | "9:16" | "1:1";
  style_prompt: string;
  bgm_url: string | null;
  bgm_prompt: string;
  bgm_volume: number;
  subtitle_srt: string;
  novel_title: string;
  shot_count: number;
  asset_count: number;
  episode_count: number;
  created_at: string;
  updated_at: string;
}

export interface Episode {
  id: string;
  project_id: string;
  order_index: number;
  title: string;
  source_text: string;
  char_count: number;
  summary: string;
  target_shots: number;
  status: "pending" | "parsed" | "produced" | string;
  shot_count: number;
  created_at: string;
}

export interface Asset {
  id: string;
  project_id: string;
  name: string;
  kind: "character" | "scene" | "prop" | "audio" | "video" | string;
  description: string;
  file_url: string | null;
  turnaround_url: string | null;
  media_type: "image" | "video" | "audio" | string;
  mime_type: string;
  thumb_url: string | null;
  size_bytes: number;
  width: number | null;
  height: number | null;
  duration_sec: number | null;
  fps: string | null;
  has_audio: boolean;
  created_at: string;
}

export interface Take {
  id: string;
  shot_id: string;
  project_id: string;
  engine: string;
  model_id: string;
  file_url: string;
  thumbnail_url: string | null;
  duration_sec: number;
  resolution: string;
  has_audio: boolean;
  prompt_used: string;
  interaction_id: string | null;
  parent_take_id: string | null;
  mode: string;
  qa_score: number | null;
  qa_feedback: string | null;
  qa_improved_prompt?: string | null;
  cost_usd: number;
  created_at: string;
}

export interface Shot {
  id: string;
  project_id: string;
  episode_id: string | null;
  order_index: number;
  title: string;
  shot_type: string;
  camera_movement: string;
  visual_prompt_zh: string;
  video_prompt_en: string;
  dialogue: string;
  dialogue_mode?: DialogueMode;
  sfx_prompt: string;
  duration_sec: number;
  asset_ids: string[];
  start_frame_url: string | null;
  end_frame_url: string | null;
  start_frame_local_path: string | null;
  end_frame_local_path: string | null;
  selected_take_id: string | null;
  trim_start: number;
  trim_end: number | null;
  takes: Take[];
  created_at: string;
}

export interface DirectorProposal {
  title?: string;
  mode?: string;
  style_prompt?: string;
  bgm_prompt?: string;
  assets?: Array<{ name: string; kind: string; description: string }>;
  shots?: Array<{
    title: string;
    shot_type: string;
    camera_movement: string;
    visual_prompt_zh: string;
    video_prompt_en: string;
    dialogue?: string;
    dialogue_mode?: DialogueMode;
    sfx_prompt?: string;
    duration_sec?: number;
    asset_names?: string[];
  }>;
}

export interface ChatMessage {
  id: string;
  project_id: string;
  role: "user" | "assistant";
  content: string;
  proposal: DirectorProposal | null;
  proposal_applied: boolean;
  created_at: string;
}

export interface JobTask {
  id: string;
  project_id: string;
  shot_id: string | null;
  asset_id?: string | null;
  kind: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  message: string;
  result: Record<string, unknown> | null;
  error: string | null;
  estimated_cost_usd: number;
  created_at: string;
  updated_at: string;
}

export interface ExportRecord {
  id: string;
  project_id: string;
  file_url: string;
  local_path: string;
  resolution: string;
  duration_sec: number;
  crossfade_sec: number;
  include_bgm: boolean;
  burn_subtitles: boolean;
  created_at: string;
}

export type StudioJobMode =
  | "text_to_video"
  | "first_frame"
  | "first_last_frame"
  | "reference_to_video"
  | "edit"
  | "extend";

export interface StudioJob {
  id: string;
  project_id: string;
  mode: StudioJobMode | string;
  status: "queued" | "uploading" | "generating" | "downloading" | "completed" | "failed";
  progress: number;
  progress_message: string;
  prompt: string;
  enhanced_prompt: string | null;
  model: string;
  aspect_ratio: "16:9" | "9:16" | string;
  duration_seconds: number;
  resolution: VideoResolution | string;
  strip_audio: boolean;
  task_override: string | null;
  first_frame_asset_id: string | null;
  last_frame_asset_id: string | null;
  source_video_asset_id: string | null;
  ref_image_asset_ids: string[];
  ref_video_asset_ids: string[];
  parent_job_id: string | null;
  previous_interaction_id: string | null;
  interaction_id: string | null;
  output_url: string | null;
  output_thumb_url: string | null;
  output_duration_seconds: number | null;
  output_width: number | null;
  output_height: number | null;
  output_has_audio: boolean;
  output_size_bytes: number | null;
  cost_usd: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface EnhancedPromptResult {
  enhanced_prompt_en: string;
  summary_zh: string;
  audio_cue: string;
  camera_notes: string;
  tips: string[];
}

export interface StudioDraftInjection {
  nonce: number;
  tabMode?: "create" | "keyframes" | "edit" | "extend";
  prompt?: string;
  enhancedPrompt?: string;
  firstFrameAssetId?: string | null;
  lastFrameAssetId?: string | null;
  sourceVideoAssetId?: string | null;
  addRefImageAssetId?: string;
}

export const VIDEO_ENGINE_OPTIONS: Array<{
  id: VideoEngine;
  label: string;
  ratePerSec: number;
  channel: string;
  desc: string;
}> = [
  {
    id: "omni_flash",
    label: "Gemini Omni 1.2 Flash",
    ratePerSec: 0.03,
    channel: "Gemini API",
    desc: "支持 3-15s / 4K / R2V / 改片续写 (~$0.03/s)",
  },
];

export function estimateVideoUsd(engine: VideoEngine, sec: number, resolution: VideoResolution = "720p"): string {
  const opt = VIDEO_ENGINE_OPTIONS.find((o) => o.id === engine);
  const mult = engine === "omni_flash" && resolution === "4k" ? 1.5 : 1.0;
  return ((opt?.ratePerSec ?? 0.05) * sec * mult).toFixed(2);
}

export interface AuthStatus {
  auth_enabled: boolean;
  initialized: boolean;
  authenticated: boolean;
  username?: string | null;
  role?: string | null;
}
