export type AppMode = "auto" | "live" | "demo";
export type VideoEngine = "veo_lite" | "veo_fast" | "veo_standard" | "omni_flash";

export interface Settings {
  app_mode: AppMode;
  effective_mode: "live" | "demo";
  has_gemini_key: boolean;
  gemini_api_key_masked: string;
  has_vertex_config: boolean;
  vertex_project_id: string;
  vertex_location: string;
  google_application_credentials: string;
  text_model: string;
  image_model: string;
  omni_video_model: string;
  veo_lite_model: string;
  veo_fast_model: string;
  veo_standard_model: string;
  music_model: string;
  monthly_budget_usd: number;
  ffmpeg_available: boolean;
  ffmpeg_path: string;
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
  kind: "character" | "scene" | "prop" | "audio";
  description: string;
  file_url: string | null;
  turnaround_url: string | null;
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
  has_audio: boolean;
  prompt_used: string;
  qa_score: number | null;
  qa_feedback: string | null;
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
  include_bgm: boolean;
  burn_subtitles: boolean;
  created_at: string;
}

export const VIDEO_ENGINE_OPTIONS: Array<{
  id: VideoEngine;
  label: string;
  ratePerSec: number;
  channel: string;
  desc: string;
}> = [
  { id: "veo_lite", label: "Veo 3.1 Lite", ratePerSec: 0.05, channel: "Vertex AI", desc: "低成本打样首选 (~$0.05/s)" },
  { id: "veo_fast", label: "Veo 3.1 Fast", ratePerSec: 0.12, channel: "Vertex AI", desc: "质量速度均衡 (~$0.12/s)" },
  { id: "veo_standard", label: "Veo 3.1 Standard", ratePerSec: 0.4, channel: "Vertex AI", desc: "电影级精渲 (~$0.40/s)" },
  { id: "omni_flash", label: "Gemini Omni 1.2 Flash", ratePerSec: 0.03, channel: "Gemini API", desc: "仅需 API Key (~$0.03/s)" },
];

export function estimateVideoUsd(engine: VideoEngine, sec: number): string {
  const opt = VIDEO_ENGINE_OPTIONS.find((o) => o.id === engine);
  return ((opt?.ratePerSec ?? 0.05) * sec).toFixed(2);
}
