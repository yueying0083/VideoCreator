import type {
  Asset,
  AuthStatus,
  BudgetSummary,
  ChatMessage,
  ConnectionTestResult,
  EnhancedPromptResult,
  Episode,
  ExportRecord,
  JobTask,
  Project,
  Settings,
  Shot,
  StudioJob,
  Take,
  VideoEngine,
  VideoResolution,
} from "./types";

let unauthorizedHandler: (() => void) | null = null;

export function setUnauthorizedHandler(cb: (() => void) | null): void {
  unauthorizedHandler = cb;
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    credentials: "same-origin",
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    if (res.status === 401 && !url.startsWith("/api/auth/") && unauthorizedHandler) {
      unauthorizedHandler();
    }
    let msg = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      msg = body.detail || JSON.stringify(body);
    } catch {
      msg = await res.text();
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export function formatBytes(bytes?: number | null): string {
  if (!bytes || bytes <= 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDuration(sec?: number | null): string {
  if (sec === null || sec === undefined) return "";
  return `${sec.toFixed(1)}s`;
}

export const api = {
  // Authentication
  getAuthStatus: () => req<AuthStatus>("/api/auth/status"),
  setupAdmin: (username: string, password: string) =>
    req<AuthStatus>("/api/auth/setup", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  login: (username: string, password: string, remember = true) =>
    req<AuthStatus>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password, remember }),
    }),
  logout: () => req<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  changePassword: (current_password: string, new_password: string) =>
    req<{ ok: boolean }>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),

  // Settings & Budget
  getSettings: () => req<Settings>("/api/settings"),
  updateSettings: (payload: Partial<Settings> & { gemini_api_key?: string; openai_api_key?: string }) =>
    req<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(payload) }),
  testConnection: (gemini_api_key?: string) =>
    req<ConnectionTestResult>("/api/settings/test-connection", {
      method: "POST",
      body: JSON.stringify({ gemini_api_key: gemini_api_key || null }),
    }),
  testOpenAIConnection: (payload: {
    openai_base_url?: string;
    openai_api_key?: string;
    openai_image_model?: string;
  }) =>
    req<ConnectionTestResult>("/api/settings/test-openai-connection", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getBudget: () => req<BudgetSummary>("/api/settings/budget"),

  // Projects
  listProjects: () => req<Project[]>("/api/projects"),
  createProject: (payload: { name: string; description?: string; aspect_ratio?: string; style_prompt?: string }) =>
    req<Project>("/api/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (id: string, payload: Partial<Project>) =>
    req<Project>(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteProject: (id: string) => req<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),

  // Novel Import & Auto-Split
  listEpisodes: (pid: string) => req<Episode[]>(`/api/projects/${pid}/novel/episodes`),
  importNovelText: (
    pid: string,
    payload: {
      novel_title: string;
      text: string;
      split_mode: "auto_chapter" | "by_length";
      chars_per_episode: number;
      replace_existing: boolean;
    }
  ) => req<Episode[]>(`/api/projects/${pid}/novel/import-text`, { method: "POST", body: JSON.stringify(payload) }),
  importNovelFile: (
    pid: string,
    file: File,
    split_mode: "auto_chapter" | "by_length",
    chars_per_episode: number,
    replace_existing: boolean
  ) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("split_mode", split_mode);
    fd.append("chars_per_episode", String(chars_per_episode));
    fd.append("replace_existing", String(replace_existing));
    return req<Episode[]>(`/api/projects/${pid}/novel/import-file`, { method: "POST", body: fd });
  },
  updateEpisode: (pid: string, eid: string, payload: Partial<Episode>) =>
    req<Episode>(`/api/projects/${pid}/novel/episodes/${eid}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteEpisode: (pid: string, eid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/novel/episodes/${eid}`, { method: "DELETE" }),
  extractBookBible: (pid: string, max_episodes = 20) =>
    req<JobTask>(`/api/projects/${pid}/novel/extract-bible`, {
      method: "POST",
      body: JSON.stringify({ max_episodes }),
    }),
  breakdownEpisode: (pid: string, eid: string, target_shots: number, replace_existing = true) =>
    req<JobTask>(`/api/projects/${pid}/novel/episodes/${eid}/breakdown`, {
      method: "POST",
      body: JSON.stringify({ target_shots, replace_existing }),
    }),

  // Assets
  listAssets: (pid: string) => req<Asset[]>(`/api/projects/${pid}/assets`),
  createAsset: (pid: string, payload: { name: string; kind: string; description: string }) =>
    req<Asset>(`/api/projects/${pid}/assets`, { method: "POST", body: JSON.stringify(payload) }),
  uploadMediaAsset: (pid: string, file: File, kind?: string, name?: string) => {
    const fd = new FormData();
    fd.append("file", file);
    if (kind) fd.append("kind", kind);
    if (name) fd.append("name", name);
    return req<Asset>(`/api/projects/${pid}/assets/upload-media`, { method: "POST", body: fd });
  },
  updateAsset: (pid: string, aid: string, payload: Partial<Asset>) =>
    req<Asset>(`/api/projects/${pid}/assets/${aid}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteAsset: (pid: string, aid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/assets/${aid}`, { method: "DELETE" }),
  uploadAssetFile: (pid: string, aid: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<Asset>(`/api/projects/${pid}/assets/${aid}/upload`, { method: "POST", body: fd });
  },
  prepAsset: (
    pid: string,
    aid: string,
    payload: { start_seconds?: number; duration?: number; strip_audio?: boolean; max_edge?: number }
  ) => req<Asset>(`/api/projects/${pid}/assets/${aid}/prep`, { method: "POST", body: JSON.stringify(payload) }),
  extractAssetFrame: (pid: string, aid: string, position: "first" | "last" | "custom" = "last", timestamp_seconds?: number) =>
    req<Asset>(`/api/projects/${pid}/assets/${aid}/extract-frame`, {
      method: "POST",
      body: JSON.stringify({ position, timestamp_seconds }),
    }),
  generateAssetImage: (pid: string, aid: string, prompt_override?: string) =>
    req<JobTask>(`/api/projects/${pid}/assets/${aid}/generate`, {
      method: "POST",
      body: JSON.stringify({ prompt_override }),
    }),
  generateAssetTurnaround: (pid: string, aid: string) =>
    req<JobTask>(`/api/projects/${pid}/assets/${aid}/turnaround`, { method: "POST" }),
  batchGenerateAssets: (
    pid: string,
    payload: { asset_ids: string[]; target: "portrait" | "turnaround" | "both"; regenerate: boolean }
  ) =>
    req<{ submitted_count: number; skipped_count: number; tasks: JobTask[] }>(
      `/api/projects/${pid}/assets/batch-generate`,
      { method: "POST", body: JSON.stringify(payload) }
    ),

  // Shots & Takes
  listShots: (pid: string) => req<Shot[]>(`/api/projects/${pid}/shots`),
  createShot: (pid: string, payload: Partial<Shot>) =>
    req<Shot>(`/api/projects/${pid}/shots`, { method: "POST", body: JSON.stringify(payload) }),
  updateShot: (pid: string, sid: string, payload: Partial<Shot>) =>
    req<Shot>(`/api/projects/${pid}/shots/${sid}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteShot: (pid: string, sid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/shots/${sid}`, { method: "DELETE" }),
  reorderShots: (pid: string, shotIds: string[]) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/shots/reorder`, {
      method: "POST",
      body: JSON.stringify(shotIds),
    }),
  generateKeyframe: (pid: string, sid: string, which: "start" | "end", prompt_override?: string) =>
    req<JobTask>(`/api/projects/${pid}/shots/${sid}/keyframe/generate`, {
      method: "POST",
      body: JSON.stringify({ which, prompt_override }),
    }),
  copyPrevShotEndFrame: (pid: string, sid: string) =>
    req<Shot>(`/api/projects/${pid}/shots/${sid}/keyframe/from-prev-end`, { method: "POST" }),
  generateVideo: (
    pid: string,
    sid: string,
    payload: { engine: VideoEngine; duration_sec: number; resolution?: VideoResolution; with_audio: boolean; use_end_frame: boolean }
  ) =>
    req<JobTask>(`/api/projects/${pid}/shots/${sid}/video/generate`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  batchGenerateShots: (
    pid: string,
    payload: {
      episode_id?: string | null;
      engine: VideoEngine;
      resolution: VideoResolution;
      with_audio: boolean;
      use_end_frame: boolean;
      only_pending: boolean;
      chain_last_frame: boolean;
    }
  ) =>
    req<{ submitted_count: number; tasks: JobTask[] }>(`/api/projects/${pid}/shots/batch-generate`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  iterateTake: (
    pid: string,
    sid: string,
    tid: string,
    payload: {
      action: "edit" | "extend";
      prompt: string;
      duration_sec: number;
      resolution: VideoResolution;
      strip_audio: boolean;
      ref_asset_ids?: string[];
    }
  ) =>
    req<JobTask>(`/api/projects/${pid}/shots/${sid}/takes/${tid}/iterate`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  importTake: (pid: string, sid: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<Take>(`/api/projects/${pid}/shots/${sid}/takes/import`, { method: "POST", body: fd });
  },
  runTakeQa: (pid: string, sid: string, tid: string) =>
    req<JobTask>(`/api/projects/${pid}/shots/${sid}/takes/${tid}/qa`, { method: "POST" }),

  // Director Chat
  listChat: (pid: string) => req<ChatMessage[]>(`/api/projects/${pid}/chat`),
  sendChat: (pid: string, content: string) =>
    req<ChatMessage>(`/api/projects/${pid}/chat`, { method: "POST", body: JSON.stringify({ content }) }),
  applyProposal: (pid: string, mid: string) =>
    req<{ ok: boolean; applied_shots: number; applied_assets: number }>(`/api/projects/${pid}/chat/${mid}/apply`, {
      method: "POST",
    }),

  // Audio & Subtitles
  generateBgm: (pid: string, prompt: string, mode: "clip" | "pro") =>
    req<JobTask>(`/api/projects/${pid}/audio/bgm/generate`, {
      method: "POST",
      body: JSON.stringify({ prompt, mode }),
    }),
  uploadBgm: (pid: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<{ bgm_url: string }>(`/api/projects/${pid}/audio/bgm/upload`, { method: "POST", body: fd });
  },
  autoSubtitles: (pid: string, episode_id?: string | null) =>
    req<{ subtitle_srt: string }>(
      `/api/projects/${pid}/audio/subtitles/auto-from-script${episode_id ? `?episode_id=${episode_id}` : ""}`,
      { method: "POST" }
    ),

  // Omni Studio Tab
  enhancePrompt: (
    pid: string,
    payload: {
      prompt: string;
      mode?: string;
      duration_seconds?: number;
      aspect_ratio?: "16:9" | "9:16";
      single_scene?: boolean;
      include_timecodes?: boolean;
      audio_preference?: string;
      style_hint?: string;
      has_first_frame?: boolean;
      has_last_frame?: boolean;
      ref_image_count?: number;
      ref_video_count?: number;
      model?: string;
    }
  ) =>
    req<EnhancedPromptResult>(`/api/projects/${pid}/studio/enhance-prompt`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listStudioJobs: (pid: string) => req<StudioJob[]>(`/api/projects/${pid}/studio/jobs`),
  createStudioJob: (
    pid: string,
    payload: {
      mode: string;
      prompt: string;
      enhanced_prompt?: string;
      aspect_ratio: "16:9" | "9:16";
      duration_seconds: number;
      resolution: VideoResolution;
      strip_audio?: boolean;
      first_frame_asset_id?: string | null;
      last_frame_asset_id?: string | null;
      source_video_asset_id?: string | null;
      ref_image_asset_ids?: string[];
      ref_video_asset_ids?: string[];
      parent_job_id?: string | null;
      previous_interaction_id?: string | null;
    }
  ) =>
    req<StudioJob>(`/api/projects/${pid}/studio/jobs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getStudioJobLineage: (pid: string, jid: string) =>
    req<StudioJob[]>(`/api/projects/${pid}/studio/jobs/${jid}/lineage`),
  extractStudioJobFrame: (pid: string, jid: string, position: "first" | "last" | "custom" = "last") =>
    req<Asset>(`/api/projects/${pid}/studio/jobs/${jid}/extract-frame`, {
      method: "POST",
      body: JSON.stringify({ position }),
    }),
  saveStudioJobAsAsset: (pid: string, jid: string) =>
    req<Asset>(`/api/projects/${pid}/studio/jobs/${jid}/save-as-asset`, { method: "POST" }),
  sendStudioJobToShot: (pid: string, jid: string, sid: string) =>
    req<Take>(`/api/projects/${pid}/studio/jobs/${jid}/send-to-shot/${sid}`, { method: "POST" }),
  deleteStudioJob: (pid: string, jid: string) =>
    req<{ deleted: boolean; id: string }>(`/api/projects/${pid}/studio/jobs/${jid}`, { method: "DELETE" }),

  // Tasks & Exports
  listTasks: (pid?: string) => req<JobTask[]>(pid ? `/api/tasks?project_id=${pid}` : "/api/tasks"),
  listExports: (pid: string) => req<ExportRecord[]>(`/api/projects/${pid}/exports`),
  createExport: (
    pid: string,
    payload: {
      episode_id?: string | null;
      resolution: "720p" | "1080p" | "4k";
      crossfade_sec?: number;
      include_bgm: boolean;
      burn_subtitles: boolean;
    }
  ) => req<JobTask>(`/api/projects/${pid}/exports`, { method: "POST", body: JSON.stringify(payload) }),
};
